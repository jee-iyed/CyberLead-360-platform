"""Pure scoring engine: boundaries, missing data, determinism, configuration validation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from cyberlead360.domain.enums import (
    Confidence,
    FactType,
    Industry,
    Priority,
    ReviewStatus,
    VerificationStatus,
)
from cyberlead360.domain.scoring_rules import (
    CompanyProfile,
    EvidenceItem,
    GeographyRule,
    NeedsRule,
    RuleSet,
    ScoringConfig,
    SizeBand,
    SizeRule,
    calculate_lead_score,
)

NOW = datetime(2026, 11, 1, tzinfo=UTC)
RULES = RuleSet(version=3, config=ScoringConfig())


def ev(
    fid: int,
    ftype: FactType,
    review: ReviewStatus = ReviewStatus.APPROVED,
    verification: VerificationStatus = VerificationStatus.VERIFIED,
) -> EvidenceItem:
    return EvidenceItem(
        fact_id=fid,
        fact_type=ftype,
        review_status=review,
        source_id=fid,
        source_verification=verification,
        confidence=Confidence.MEDIUM,
    )


def crit(result, key):  # type: ignore[no-untyped-def]
    return next(c for c in result.breakdown if c.key == key)


def test_perfect_fit_scores_100_with_high_priority_and_confidence() -> None:
    company = CompanyProfile(industry=Industry.HEALTHCARE, employee_count=500, country="FR")
    result = calculate_lead_score(company, [ev(1, FactType.SECURITY_NEED_EXPLICIT)], RULES, now=NOW)
    assert result.total_score == 100
    assert result.priority == Priority.HIGH
    assert result.data_completeness == 1.0
    assert result.evidence_confidence == Confidence.HIGH
    assert result.rules_version == 3
    assert result.calculated_at == NOW
    assert crit(result, "needs").evidence_fact_ids == [1]


def test_missing_data_is_distinguished_from_negative_evidence() -> None:
    unknown = calculate_lead_score(CompanyProfile(), [], RULES, now=NOW)
    assert unknown.total_score == 0
    assert {c.status for c in unknown.breakdown} == {"missing"}
    assert unknown.data_completeness == 0.0
    assert "Industry" in unknown.missing_information

    reviewed_no_need = calculate_lead_score(
        CompanyProfile(industry=Industry.OTHER, employee_count=10, country="US"),
        [ev(5, FactType.BUSINESS_CONTEXT)],
        RULES,
        now=NOW,
    )
    assert crit(reviewed_no_need, "needs").status == "no_evidence"
    assert crit(reviewed_no_need, "geography").status == "no_match"
    assert reviewed_no_need.data_completeness == 1.0


def test_signal_scores_partial_and_explicit_beats_signal() -> None:
    company = CompanyProfile(industry=Industry.TECHNOLOGY, employee_count=100, country="DE")
    signal = calculate_lead_score(company, [ev(1, FactType.SECURITY_SIGNAL)], RULES, now=NOW)
    assert crit(signal, "needs").points == 20
    assert crit(signal, "needs").status == "partial"
    both = calculate_lead_score(
        company,
        [ev(1, FactType.SECURITY_SIGNAL), ev(2, FactType.SECURITY_NEED_EXPLICIT)],
        RULES,
        now=NOW,
    )
    assert crit(both, "needs").points == 35
    assert crit(both, "needs").evidence_fact_ids == [2]


@pytest.mark.parametrize(
    ("review", "verification"),
    [
        (ReviewStatus.PENDING, VerificationStatus.VERIFIED),
        (ReviewStatus.REJECTED, VerificationStatus.VERIFIED),
        (ReviewStatus.APPROVED, VerificationStatus.REJECTED),
    ],
)
def test_unreviewed_or_rejected_evidence_is_ignored(review, verification) -> None:  # type: ignore[no-untyped-def]
    result = calculate_lead_score(
        CompanyProfile(industry=Industry.HEALTHCARE, employee_count=300, country="FR"),
        [ev(1, FactType.SECURITY_NEED_EXPLICIT, review, verification)],
        RULES,
        now=NOW,
    )
    assert crit(result, "needs").points == 0


def test_pending_facts_are_listed_as_missing_information() -> None:
    result = calculate_lead_score(
        CompanyProfile(industry=Industry.HEALTHCARE),
        [ev(1, FactType.SECURITY_SIGNAL, ReviewStatus.PENDING)],
        RULES,
        now=NOW,
    )
    assert any("awaiting human review" in m for m in result.missing_information)


def test_require_verified_source_option() -> None:
    cfg = ScoringConfig(needs=NeedsRule(require_verified_source=True))
    result = calculate_lead_score(
        CompanyProfile(industry=Industry.HEALTHCARE),
        [ev(1, FactType.SECURITY_NEED_EXPLICIT, verification=VerificationStatus.UNVERIFIED)],
        RuleSet(version=1, config=cfg),
        now=NOW,
    )
    assert crit(result, "needs").points == 0


@pytest.mark.parametrize(
    ("employees", "points"),
    [(1, 4), (49, 4), (50, 12), (249, 12), (250, 20), (999, 20), (1000, 16), (5000, 10)],
)
def test_size_band_boundaries(employees: int, points: int) -> None:
    result = calculate_lead_score(CompanyProfile(employee_count=employees), [], RULES, now=NOW)
    assert crit(result, "size").points == points


@pytest.mark.parametrize(
    ("score_inputs", "priority"),
    [
        # 30 + 20 + 20 + 0 = 70 → exactly the high threshold
        ({"industry": Industry.HEALTHCARE, "employee_count": 300, "country": "US"}, Priority.HIGH),
        # 30 + 12 + 0 + 0 = 42 → below medium (45)
        ({"industry": Industry.HEALTHCARE, "employee_count": 100, "country": "US"}, Priority.LOW),
    ],
)
def test_priority_threshold_boundaries(score_inputs, priority) -> None:  # type: ignore[no-untyped-def]
    evidence = [ev(1, FactType.SECURITY_SIGNAL)] if score_inputs["employee_count"] == 300 else []
    result = calculate_lead_score(CompanyProfile(**score_inputs), evidence, RULES, now=NOW)
    assert result.priority == priority


def test_scoring_is_deterministic() -> None:
    company = CompanyProfile(industry=Industry.FINANCIAL_SERVICES, employee_count=800, country="BE")
    evidence = [ev(3, FactType.REGULATORY_CONTEXT), ev(9, FactType.GROWTH_EVENT)]
    first = calculate_lead_score(company, evidence, RULES, now=NOW)
    second = calculate_lead_score(company, list(reversed(evidence)), RULES, now=NOW)
    assert first.model_dump() == second.model_dump()


def test_explanation_never_claims_probability() -> None:
    result = calculate_lead_score(CompanyProfile(industry=Industry.RETAIL), [], RULES, now=NOW)
    assert "not a probability" in result.explanation


def test_config_must_total_100() -> None:
    with pytest.raises(ValidationError, match="add up to 100"):
        ScoringConfig(geography=GeographyRule(max_points=20, primary_points=20))


def test_config_rejects_overlapping_size_bands() -> None:
    with pytest.raises(ValidationError, match="overlap"):
        SizeRule(
            bands=[
                SizeBand(min_employees=1, max_employees=100, points=5),
                SizeBand(min_employees=50, max_employees=200, points=5),
            ]
        )


def test_config_rejects_inconsistent_needs_points() -> None:
    with pytest.raises(ValidationError):
        NeedsRule(explicit_points=10, signal_points=20)


def test_config_roundtrips_through_json() -> None:
    cfg = ScoringConfig()
    restored = ScoringConfig.model_validate(cfg.model_dump(mode="json"))
    assert restored == cfg
