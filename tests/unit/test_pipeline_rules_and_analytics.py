"""Stage-transition rules and KPI formulas (pure functions on DataFrames)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from cyberlead360.domain.enums import OpportunityStage, ProspectStage
from cyberlead360.domain.exceptions import InvalidTransitionError
from cyberlead360.domain.pipeline_rules import (
    PROSPECT_TRANSITIONS,
    validate_opportunity_transition,
    validate_prospect_transition,
)
from cyberlead360.services.analytics_service import AnalyticsFrames, compute_kpis, safe_rate

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


def test_every_stage_has_transition_rules() -> None:
    assert set(PROSPECT_TRANSITIONS) == set(ProspectStage)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ProspectStage.NEW, ProspectStage.RESEARCHING),
        (ProspectStage.READY_TO_CONTACT, ProspectStage.CONTACTED),
        (ProspectStage.PROPOSAL_SENT, ProspectStage.WON),
        (ProspectStage.LOST, ProspectStage.RESEARCHING),
        (ProspectStage.ARCHIVED, ProspectStage.NEW),
    ],
)
def test_valid_transitions(current: ProspectStage, target: ProspectStage) -> None:
    validate_prospect_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ProspectStage.NEW, ProspectStage.WON),
        (ProspectStage.NEW, ProspectStage.CONTACTED),
        (ProspectStage.OPPORTUNITY_OPEN, ProspectStage.ARCHIVED),
        (ProspectStage.QUALIFIED, ProspectStage.QUALIFIED),
    ],
)
def test_invalid_transitions(current: ProspectStage, target: ProspectStage) -> None:
    with pytest.raises(InvalidTransitionError):
        validate_prospect_transition(current, target)


def test_opportunity_transitions() -> None:
    validate_opportunity_transition(OpportunityStage.OPEN, OpportunityStage.WON)
    with pytest.raises(InvalidTransitionError):
        validate_opportunity_transition(OpportunityStage.WON, OpportunityStage.OPEN)


def test_safe_rate_handles_zero_denominator() -> None:
    assert safe_rate(0, 0) is None
    assert safe_rate(1, 4) == 0.25


def _frames(companies, activities, opportunities, meetings) -> AnalyticsFrames:  # type: ignore[no-untyped-def]
    return AnalyticsFrames(
        companies=pd.DataFrame(
            companies,
            columns=[
                "company_id",
                "company_name",
                "industry",
                "country",
                "stage",
                "highest_stage_order",
                "archived_at",
                "created_at",
                "lead_score",
            ],
        ),
        activities=pd.DataFrame(
            activities,
            columns=[
                "activity_id",
                "company_id",
                "contact_id",
                "activity_type",
                "occurred_at",
                "follow_up_at",
                "follow_up_done",
            ],
        ),
        opportunities=pd.DataFrame(
            opportunities,
            columns=[
                "opportunity_id",
                "company_id",
                "stage",
                "value",
                "probability",
                "created_at",
                "closed_at",
            ],
        ),
        meetings=pd.DataFrame(
            meetings, columns=["meeting_id", "company_id", "scheduled_at", "status"]
        ),
    )


def test_kpis_count_distinct_companies_and_use_documented_denominators() -> None:
    t = NOW - timedelta(days=3)
    companies = [
        (1, "A", "healthcare", "FR", "replied", 6, None, t, 80),
        (2, "B", "technology", "FR", "contacted", 5, None, t, 60),
        (3, "C", "retail", "FR", "new", 1, None, t, None),
        (4, "D", "retail", "FR", "won", 10, None, t, 70),
    ]
    activities = [
        # company 1 e-mailed three times: still ONE contacted company
        (1, 1, None, "email_sent", t, None, False),
        (2, 1, None, "email_sent", t, None, False),
        (3, 1, None, "call", t, None, False),
        (4, 1, None, "reply_received", t, None, False),
        (5, 2, None, "email_sent", t, NOW - timedelta(days=1), False),  # overdue follow-up
        (6, 4, None, "email_sent", t, NOW + timedelta(hours=1), False),  # due today
        (7, 4, None, "reply_received", t, None, False),
        (8, 3, None, "reply_received", t, None, False),  # inbound w/o outbound: not counted
    ]
    opportunities = [
        (1, 4, "won", 10000.0, 100, t, t),
        (2, 1, "open", 20000.0, 50, t, None),
        (3, 2, "lost", 5000.0, 0, t, t),
    ]
    meetings = [(1, 1, t, "held"), (2, 2, t, "cancelled")]
    k = compute_kpis(_frames(companies, activities, opportunities, meetings), now=NOW)

    assert k.contacted == 3  # companies 1, 2, 4
    assert k.replied == 2  # companies 1 and 4 (3 never contacted)
    assert k.response_rate == pytest.approx(2 / 3, abs=1e-4)
    assert k.companies_with_meeting == 1  # cancelled meeting excluded
    assert k.meeting_rate == pytest.approx(1 / 3, abs=1e-4)
    assert k.qualified == 3  # highest stage >= qualified (3)
    assert k.lead_to_opportunity == pytest.approx(1.0)  # companies 1, 2, 4 all have deals
    assert k.win_rate == 0.5  # 1 won / (1 won + 1 lost)
    assert k.pipeline_value == 20000.0
    assert k.weighted_pipeline_value == 10000.0
    assert k.follow_ups_due == 2 and k.follow_ups_overdue == 1
    assert k.average_lead_score == 70.0  # mean of 80, 60, 70 (None ignored)


def test_kpis_on_empty_data_do_not_crash() -> None:
    k = compute_kpis(_frames([], [], [], []), now=NOW)
    assert k.companies == 0
    assert k.response_rate is None and k.win_rate is None and k.average_lead_score is None
