"""Scoring orchestration: rule versions, evidence loading, persistence, recalculation."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from cyberlead360.database.models import (
    Company,
    CompanyFact,
    CompanySource,
    ScoringResult,
    ScoringRule,
)
from cyberlead360.database.repositories.activities import AuditRepository
from cyberlead360.database.repositories.intelligence import IntelligenceRepository
from cyberlead360.domain.enums import (
    Confidence,
    FactType,
    Industry,
    ReviewStatus,
    VerificationStatus,
)
from cyberlead360.domain.exceptions import NotFoundError
from cyberlead360.domain.scoring_rules import (
    CompanyProfile,
    EvidenceItem,
    LeadScoreResult,
    RuleSet,
    ScoringConfig,
    calculate_lead_score,
)
from cyberlead360.utils.date_utils import utcnow


class ScoringService:
    def __init__(self, session: Session, actor: str) -> None:
        self.s = session
        self.actor = actor
        self.repo = IntelligenceRepository(session)
        self.audit = AuditRepository(session)

    # ------------------------------------------------------------------ rules
    def ensure_default_rules(self) -> ScoringRule:
        rule = self.repo.active_rule()
        if rule is None:
            rule = self.repo.add_rule(
                ScoringRule(
                    version=self.repo.max_rule_version() + 1,
                    config=ScoringConfig().model_dump(mode="json"),
                    is_active=True,
                    notes="Default rule set",
                    created_by=self.actor,
                )
            )
            self.audit.record(
                "scoring_rule", rule.id, "created", self.actor, {"version": rule.version}
            )
        return rule

    def active_ruleset(self) -> tuple[ScoringRule, RuleSet]:
        rule = self.ensure_default_rules()
        return rule, RuleSet(version=rule.version, config=ScoringConfig.model_validate(rule.config))

    def publish_rules(self, config: ScoringConfig, notes: str | None = None) -> ScoringRule:
        """Store a new rule version and make it active. Scores are NOT recalculated here."""
        self.repo.deactivate_rules()
        rule = self.repo.add_rule(
            ScoringRule(
                version=self.repo.max_rule_version() + 1,
                config=config.model_dump(mode="json"),
                is_active=True,
                notes=notes,
                created_by=self.actor,
            )
        )
        self.audit.record(
            "scoring_rule", rule.id, "published", self.actor, {"version": rule.version}
        )
        return rule

    # ------------------------------------------------------------------ scoring
    def evidence_for(self, company_id: int) -> list[EvidenceItem]:
        rows = self.s.execute(
            select(CompanyFact, CompanySource.verification_status)
            .join(CompanySource, CompanySource.id == CompanyFact.source_id)
            .where(CompanyFact.company_id == company_id)
        ).all()
        return [
            EvidenceItem(
                fact_id=f.id,
                fact_type=FactType(f.fact_type),
                review_status=ReviewStatus(f.review_status),
                source_id=f.source_id,
                source_verification=VerificationStatus(v),
                confidence=Confidence(f.confidence),
                observed_at=f.observed_at,
            )
            for f, v in rows
        ]

    @staticmethod
    def profile_of(company: Company) -> CompanyProfile:
        return CompanyProfile(
            company_id=company.id,
            industry=Industry(company.industry) if company.industry else None,
            employee_count=company.employee_count,
            country=company.country,
        )

    def preview(self, company_id: int, config: ScoringConfig | None = None) -> LeadScoreResult:
        company = self.s.get(Company, company_id)
        if company is None:
            raise NotFoundError("Company", company_id)
        rule, ruleset = self.active_ruleset()
        if config is not None:
            ruleset = RuleSet(version=rule.version + 1, config=config)
        return calculate_lead_score(
            self.profile_of(company), self.evidence_for(company_id), ruleset
        )

    def score_company(self, company_id: int, *, now: datetime | None = None) -> ScoringResult:
        company = self.s.get(Company, company_id)
        if company is None:
            raise NotFoundError("Company", company_id)
        rule, ruleset = self.active_ruleset()
        result = calculate_lead_score(
            self.profile_of(company), self.evidence_for(company_id), ruleset, now=now or utcnow()
        )
        return self.repo.add_score(
            ScoringResult(
                company_id=company_id,
                scoring_rule_id=rule.id,
                rules_version=result.rules_version,
                total_score=result.total_score,
                priority=result.priority.value,
                breakdown=[c.model_dump(mode="json") for c in result.breakdown],
                missing_information=result.missing_information,
                explanation=result.explanation,
                data_completeness=result.data_completeness,
                evidence_confidence=result.evidence_confidence.value,
                calculated_at=result.calculated_at,
            )
        )

    def recalculate_all(self, *, include_archived: bool = False) -> int:
        stmt = select(Company.id).where(Company.merged_into_id.is_(None))
        if not include_archived:
            stmt = stmt.where(Company.archived_at.is_(None))
        ids = list(self.s.scalars(stmt))
        now = utcnow()
        for cid in ids:
            self.score_company(cid, now=now)
        self.audit.record("scoring_rule", None, "recalculated", self.actor, {"companies": len(ids)})
        return len(ids)

    def stale_count(self) -> int:
        rule, _ = self.active_ruleset()
        return sum(
            1
            for r in self.s.scalars(
                select(ScoringResult.rules_version)
                .join(Company, Company.id == ScoringResult.company_id)
                .where(ScoringResult.is_current.is_(True), Company.archived_at.is_(None))
            )
            if r != rule.version
        )

    def impact_preview(self, config: ScoringConfig) -> pd.DataFrame:
        """Scores of active companies under the active rules vs ``config`` (nothing saved)."""
        rule, current = self.active_ruleset()
        candidate = RuleSet(version=rule.version + 1, config=config)
        rows = []
        for company in self.s.scalars(select(Company).where(Company.archived_at.is_(None))):
            profile, evidence = self.profile_of(company), self.evidence_for(company.id)
            rows.append(
                {
                    "company_id": company.id,
                    "before": calculate_lead_score(profile, evidence, current).total_score,
                    "after": calculate_lead_score(profile, evidence, candidate).total_score,
                }
            )
        return pd.DataFrame(rows, columns=["company_id", "before", "after"])

    def ranking(self) -> pd.DataFrame:
        rows = self.s.execute(
            select(
                Company.id,
                Company.company_name,
                Company.industry,
                Company.country,
                Company.employee_count,
                Company.prospect_stage,
                ScoringResult.total_score,
                ScoringResult.priority,
                ScoringResult.data_completeness,
                ScoringResult.evidence_confidence,
                ScoringResult.rules_version,
                ScoringResult.calculated_at,
            )
            .join(
                ScoringResult,
                (ScoringResult.company_id == Company.id) & ScoringResult.is_current.is_(True),
            )
            .where(Company.archived_at.is_(None))
        ).all()
        df = pd.DataFrame(
            rows,
            columns=[
                "id",
                "company",
                "industry",
                "country",
                "employees",
                "stage",
                "score",
                "priority",
                "completeness",
                "confidence",
                "rules_version",
                "calculated_at",
            ],
        )
        if df.empty:
            return df
        return df.sort_values(
            ["score", "completeness", "company"], ascending=[False, False, True]
        ).reset_index(drop=True)
