"""Transparent, rule-based lead scoring engine (pure domain logic).

The score answers ONE question: *how well does this company fit our commercial
targeting, based on documented evidence?* It is NOT a probability of
conversion and NOT a cybersecurity risk assessment. No LLM is involved.

Design rules
------------
* Every criterion returns points, a status and a human-readable reason.
* ``missing`` (we do not know) is kept distinct from ``no_match`` / ``no_evidence``
  (we know, and it does not fit).
* Data completeness and evidence confidence are reported separately from the score.
* Only firmographic attributes of the *company* are used — never personal or
  sensitive attributes of individuals.
"""

from __future__ import annotations

import itertools
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from cyberlead360.domain.enums import (
    Confidence,
    FactType,
    Industry,
    Priority,
    ReviewStatus,
    VerificationStatus,
)
from cyberlead360.utils.date_utils import utcnow
from cyberlead360.utils.normalization import country_name

CriterionStatus = Literal["matched", "partial", "no_match", "no_evidence", "missing"]

NEED_EXPLICIT_TYPES = frozenset({FactType.SECURITY_NEED_EXPLICIT})
NEED_SIGNAL_TYPES = frozenset({FactType.SECURITY_SIGNAL, FactType.REGULATORY_CONTEXT})


# --------------------------------------------------------------------------- config
class IndustryRule(BaseModel):
    max_points: int = Field(30, ge=0)
    points: dict[Industry, int] = Field(
        default_factory=lambda: {
            Industry.MANUFACTURING: 30,
            Industry.HEALTHCARE: 30,
            Industry.FINANCIAL_SERVICES: 30,
            Industry.ENERGY_UTILITIES: 28,
            Industry.TECHNOLOGY: 25,
            Industry.TELECOM: 22,
            Industry.LOGISTICS: 20,
            Industry.PUBLIC_SECTOR: 18,
            Industry.RETAIL: 15,
            Industry.PROFESSIONAL_SERVICES: 12,
            Industry.EDUCATION: 10,
            Industry.OTHER: 5,
        }
    )
    default_points: int = Field(5, ge=0)

    @model_validator(mode="after")
    def _bounded(self) -> IndustryRule:
        too_high = [k for k, v in self.points.items() if v > self.max_points or v < 0]
        if too_high or self.default_points > self.max_points:
            raise ValueError("Industry points must be between 0 and max_points")
        return self


class SizeBand(BaseModel):
    min_employees: int = Field(ge=1)
    max_employees: int | None = Field(default=None, ge=1)
    points: int = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> SizeBand:
        if self.max_employees is not None and self.max_employees < self.min_employees:
            raise ValueError("max_employees must be >= min_employees")
        return self

    def contains(self, count: int) -> bool:
        return count >= self.min_employees and (
            self.max_employees is None or count <= self.max_employees
        )

    @property
    def label(self) -> str:
        if self.max_employees is None:
            return f"{self.min_employees}+"
        return f"{self.min_employees}–{self.max_employees}"


class SizeRule(BaseModel):
    max_points: int = Field(20, ge=0)
    bands: list[SizeBand] = Field(
        default_factory=lambda: [
            SizeBand(min_employees=1, max_employees=49, points=4),
            SizeBand(min_employees=50, max_employees=249, points=12),
            SizeBand(min_employees=250, max_employees=999, points=20),
            SizeBand(min_employees=1000, max_employees=4999, points=16),
            SizeBand(min_employees=5000, max_employees=None, points=10),
        ]
    )

    @model_validator(mode="after")
    def _non_overlapping(self) -> SizeRule:
        ordered = sorted(self.bands, key=lambda b: b.min_employees)
        for prev, nxt in itertools.pairwise(ordered):
            if prev.max_employees is None or prev.max_employees >= nxt.min_employees:
                raise ValueError("Size bands must not overlap")
        if any(b.points > self.max_points for b in self.bands):
            raise ValueError("Size band points must not exceed max_points")
        self.bands = ordered
        return self


class NeedsRule(BaseModel):
    max_points: int = Field(35, ge=0)
    explicit_points: int = Field(35, ge=0)
    signal_points: int = Field(20, ge=0)
    none_points: int = Field(0, ge=0)
    require_verified_source: bool = Field(
        default=False,
        description="If true, only facts whose source is VERIFIED count as evidence.",
    )

    @model_validator(mode="after")
    def _bounded(self) -> NeedsRule:
        if not (self.none_points <= self.signal_points <= self.explicit_points <= self.max_points):
            raise ValueError("Require none <= signal <= explicit <= max_points")
        return self


class GeographyRule(BaseModel):
    max_points: int = Field(15, ge=0)
    primary_countries: list[str] = Field(
        default_factory=lambda: ["FR", "BE", "CH", "LU"], validate_default=True
    )
    primary_points: int = Field(15, ge=0)
    secondary_countries: list[str] = Field(
        default_factory=lambda: ["DE", "NL", "ES", "IT", "GB", "MA", "TN"], validate_default=True
    )
    secondary_points: int = Field(8, ge=0)
    other_points: int = Field(0, ge=0)

    @field_validator("primary_countries", "secondary_countries")
    @classmethod
    def _upper(cls, value: list[str]) -> list[str]:
        return sorted({c.strip().upper() for c in value if c.strip()})

    @model_validator(mode="after")
    def _bounded(self) -> GeographyRule:
        if set(self.primary_countries) & set(self.secondary_countries):
            raise ValueError("A country cannot be both primary and secondary")
        if max(self.primary_points, self.secondary_points, self.other_points) > self.max_points:
            raise ValueError("Geography points must not exceed max_points")
        return self


class PriorityThresholds(BaseModel):
    high: int = Field(70, ge=0, le=100)
    medium: int = Field(45, ge=0, le=100)

    @model_validator(mode="after")
    def _ordered(self) -> PriorityThresholds:
        if self.medium > self.high:
            raise ValueError("Medium threshold must be <= high threshold")
        return self


class ScoringConfig(BaseModel):
    """Full, serializable scoring configuration. Stored as JSON per rule version."""

    industry: IndustryRule = Field(default_factory=IndustryRule)
    size: SizeRule = Field(default_factory=SizeRule)
    needs: NeedsRule = Field(default_factory=NeedsRule)
    geography: GeographyRule = Field(default_factory=GeographyRule)
    priority: PriorityThresholds = Field(default_factory=PriorityThresholds)

    @model_validator(mode="after")
    def _total_is_100(self) -> ScoringConfig:
        total = self.max_score
        if total != 100:
            raise ValueError(f"Criterion maxima must add up to 100 (currently {total}).")
        return self

    @property
    def max_score(self) -> int:
        return (
            self.industry.max_points
            + self.size.max_points
            + self.needs.max_points
            + self.geography.max_points
        )


class RuleSet(BaseModel):
    """A versioned configuration, as passed to the engine."""

    version: int = Field(ge=1)
    config: ScoringConfig


# --------------------------------------------------------------------------- inputs
class CompanyProfile(BaseModel):
    """Only company-level firmographics. No personal attributes, by design."""

    company_id: int | None = None
    industry: Industry | None = None
    employee_count: int | None = Field(default=None, ge=1)
    country: str | None = None


class EvidenceItem(BaseModel):
    fact_id: int
    fact_type: FactType
    review_status: ReviewStatus
    source_id: int
    source_verification: VerificationStatus
    confidence: Confidence = Confidence.MEDIUM
    observed_at: datetime | None = None


# --------------------------------------------------------------------------- outputs
class CriterionResult(BaseModel):
    key: Literal["industry", "size", "needs", "geography"]
    label: str
    points: int
    max_points: int
    status: CriterionStatus
    reason: str
    evidence_fact_ids: list[int] = Field(default_factory=list)


class LeadScoreResult(BaseModel):
    total_score: int
    max_score: int
    priority: Priority
    breakdown: list[CriterionResult]
    rules_version: int
    explanation: str
    missing_information: list[str]
    data_completeness: float = Field(ge=0, le=1)
    evidence_confidence: Confidence
    calculated_at: datetime


# --------------------------------------------------------------------------- engine
def _score_industry(company: CompanyProfile, rule: IndustryRule) -> CriterionResult:
    if company.industry is None:
        return CriterionResult(
            key="industry",
            label="Industry fit",
            points=0,
            max_points=rule.max_points,
            status="missing",
            reason="Industry is unknown — not scored.",
        )
    points = rule.points.get(company.industry, rule.default_points)
    status: CriterionStatus = (
        "matched" if points == rule.max_points else "partial" if points > 0 else "no_match"
    )
    return CriterionResult(
        key="industry",
        label="Industry fit",
        points=points,
        max_points=rule.max_points,
        status=status,
        reason=f"Industry '{company.industry.label}' is weighted {points}/{rule.max_points}.",
    )


def _score_size(company: CompanyProfile, rule: SizeRule) -> CriterionResult:
    if company.employee_count is None:
        return CriterionResult(
            key="size",
            label="Company size",
            points=0,
            max_points=rule.max_points,
            status="missing",
            reason="Employee count is unknown — not scored.",
        )
    for band in rule.bands:
        if band.contains(company.employee_count):
            status: CriterionStatus = (
                "matched"
                if band.points == rule.max_points
                else "partial"
                if band.points > 0
                else "no_match"
            )
            return CriterionResult(
                key="size",
                label="Company size",
                points=band.points,
                max_points=rule.max_points,
                status=status,
                reason=(
                    f"{company.employee_count} employees falls in band {band.label} "
                    f"({band.points}/{rule.max_points})."
                ),
            )
    return CriterionResult(
        key="size",
        label="Company size",
        points=0,
        max_points=rule.max_points,
        status="no_match",
        reason=f"{company.employee_count} employees is outside every configured band.",
    )


def _usable(item: EvidenceItem, rule: NeedsRule) -> bool:
    if item.review_status != ReviewStatus.APPROVED:
        return False
    if item.source_verification == VerificationStatus.REJECTED:
        return False
    return not (
        rule.require_verified_source and item.source_verification != VerificationStatus.VERIFIED
    )


def _score_needs(evidence: list[EvidenceItem], rule: NeedsRule) -> CriterionResult:
    usable = [e for e in evidence if _usable(e, rule)]
    explicit = sorted(e.fact_id for e in usable if e.fact_type in NEED_EXPLICIT_TYPES)
    signals = sorted(e.fact_id for e in usable if e.fact_type in NEED_SIGNAL_TYPES)
    base = {"key": "needs", "label": "Documented cybersecurity need", "max_points": rule.max_points}
    if explicit:
        return CriterionResult(
            **base,
            points=rule.explicit_points,
            status="matched",
            evidence_fact_ids=explicit,
            reason=f"Explicit, sourced need documented in fact(s) {_ids(explicit)}.",
        )
    if signals:
        return CriterionResult(
            **base,
            points=rule.signal_points,
            status="partial",
            evidence_fact_ids=signals,
            reason=(
                f"Relevant public signal in fact(s) {_ids(signals)}; no explicit need documented."
            ),
        )
    if not usable:
        return CriterionResult(
            **base,
            points=rule.none_points,
            status="missing",
            reason="No reviewed and approved facts yet — research needed (unknown, not negative).",
        )
    return CriterionResult(
        **base,
        points=rule.none_points,
        status="no_evidence",
        reason=(f"{len(usable)} approved fact(s) reviewed; none documents a cybersecurity need."),
    )


def _score_geography(company: CompanyProfile, rule: GeographyRule) -> CriterionResult:
    base = {"key": "geography", "label": "Geographic fit", "max_points": rule.max_points}
    if not company.country:
        return CriterionResult(
            **base, points=0, status="missing", reason="Country is unknown — not scored."
        )
    code = company.country.upper()
    name = country_name(code)
    if code in rule.primary_countries:
        return CriterionResult(
            **base,
            points=rule.primary_points,
            status="matched",
            reason=f"{name} is a primary target market.",
        )
    if code in rule.secondary_countries:
        return CriterionResult(
            **base,
            points=rule.secondary_points,
            status="partial",
            reason=f"{name} is a secondary target market.",
        )
    return CriterionResult(
        **base,
        points=rule.other_points,
        status="no_match",
        reason=f"{name} is outside the configured target markets.",
    )


def _ids(ids: list[int]) -> str:
    return ", ".join(f"#{i}" for i in ids)


def _priority(total: int, thresholds: PriorityThresholds) -> Priority:
    if total >= thresholds.high:
        return Priority.HIGH
    if total >= thresholds.medium:
        return Priority.MEDIUM
    return Priority.LOW


def _confidence(
    completeness: float, needs: CriterionResult, evidence: list[EvidenceItem]
) -> Confidence:
    verified_ids = {
        e.fact_id for e in evidence if e.source_verification == VerificationStatus.VERIFIED
    }
    needs_verified = bool(needs.evidence_fact_ids) and set(needs.evidence_fact_ids) <= verified_ids
    if completeness == 1.0 and needs_verified:
        return Confidence.HIGH
    if completeness >= 0.75:
        return Confidence.MEDIUM
    return Confidence.LOW


def calculate_lead_score(
    company: CompanyProfile,
    evidence: list[EvidenceItem],
    rules: RuleSet,
    *,
    now: datetime | None = None,
) -> LeadScoreResult:
    """Compute a deterministic, explainable lead score.

    Same inputs (and same ``now``) always yield the same output.
    """
    cfg = rules.config
    breakdown = [
        _score_industry(company, cfg.industry),
        _score_size(company, cfg.size),
        _score_needs(evidence, cfg.needs),
        _score_geography(company, cfg.geography),
    ]
    total = sum(c.points for c in breakdown)
    priority = _priority(total, cfg.priority)

    missing: list[str] = []
    for c in breakdown:
        if c.status == "missing":
            missing.append(
                {
                    "industry": "Industry",
                    "size": "Employee count",
                    "needs": "Reviewed evidence of a cybersecurity need",
                    "geography": "Country",
                }[c.key]
            )
    pending = sum(1 for e in evidence if e.review_status == ReviewStatus.PENDING)
    if pending:
        missing.append(f"{pending} fact(s) awaiting human review (not counted)")

    known = sum(1 for c in breakdown if c.status != "missing")
    completeness = round(known / len(breakdown), 2)
    confidence = _confidence(completeness, breakdown[2], evidence)

    strongest = max(breakdown, key=lambda c: c.points / c.max_points if c.max_points else 0)
    explanation = (
        f"Score {total}/{cfg.max_score} → {priority.value} priority (rules v{rules.version}). "
        f"Strongest factor: {strongest.label.lower()} ({strongest.points}/{strongest.max_points}). "
        f"Data completeness {int(completeness * 100)}%, evidence confidence {confidence.value}. "
        "This is a targeting-fit score, not a probability of conversion or a security risk rating."
    )
    return LeadScoreResult(
        total_score=total,
        max_score=cfg.max_score,
        priority=priority,
        breakdown=breakdown,
        rules_version=rules.version,
        explanation=explanation,
        missing_information=missing,
        data_completeness=completeness,
        evidence_confidence=confidence,
        calculated_at=now or utcnow(),
    )
