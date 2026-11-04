"""Sales analytics: KPI definitions with explicit denominators.

All funnel metrics count DISTINCT COMPANIES (not messages), so repeated
interactions with the same prospect are not double-counted.

Population: every company that was not merged into another record (archived
and lost companies are included so historical conversion is not inflated).

* Response rate      = contacted companies that replied / contacted companies
* Meeting rate       = contacted companies with a meeting / contacted companies
* Lead→opportunity   = qualified companies with ≥1 opportunity / qualified companies
* Win rate           = won opportunities / closed (won + lost) opportunities

A rate whose denominator is 0 is reported as ``None`` ("n/a"), never 0 %.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, time, timedelta

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from cyberlead360.database.models import Activity, Company, Meeting, Opportunity, ScoringResult
from cyberlead360.domain.enums import ActivityType, Industry, MeetingStatus, ProspectStage

OUTBOUND_TYPES = [t.value for t in ActivityType if t.is_outbound_touch]
OPEN_OPP_STAGES = ["open", "proposal_sent"]
VALID_MEETING_STATUSES = [MeetingStatus.SCHEDULED.value, MeetingStatus.HELD.value]


@dataclass
class AnalyticsFrames:
    companies: pd.DataFrame
    activities: pd.DataFrame
    opportunities: pd.DataFrame
    meetings: pd.DataFrame


@dataclass
class KPIs:
    companies: int
    qualified: int
    contacted: int
    replied: int
    companies_with_meeting: int
    meetings_total: int
    open_opportunities: int
    won_opportunities: int
    lost_opportunities: int
    response_rate: float | None
    meeting_rate: float | None
    lead_to_opportunity: float | None
    win_rate: float | None
    pipeline_value: float
    weighted_pipeline_value: float
    won_value: float
    average_lead_score: float | None
    follow_ups_due: int
    follow_ups_overdue: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def safe_rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def load_frames(session: Session) -> AnalyticsFrames:
    score = (
        select(ScoringResult.company_id, ScoringResult.total_score)
        .where(ScoringResult.is_current.is_(True))
        .subquery()
    )
    companies = pd.DataFrame(
        session.execute(
            select(
                Company.id,
                Company.company_name,
                Company.industry,
                Company.country,
                Company.prospect_stage,
                Company.highest_stage_order,
                Company.archived_at,
                Company.created_at,
                score.c.total_score,
            )
            .outerjoin(score, score.c.company_id == Company.id)
            .where(Company.merged_into_id.is_(None))
        ).all(),
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
    )
    activities = pd.DataFrame(
        session.execute(
            select(
                Activity.id,
                Activity.company_id,
                Activity.contact_id,
                Activity.activity_type,
                Activity.occurred_at,
                Activity.follow_up_at,
                Activity.follow_up_done,
            )
        ).all(),
        columns=[
            "activity_id",
            "company_id",
            "contact_id",
            "activity_type",
            "occurred_at",
            "follow_up_at",
            "follow_up_done",
        ],
    )
    opportunities = pd.DataFrame(
        session.execute(
            select(
                Opportunity.id,
                Opportunity.company_id,
                Opportunity.stage,
                Opportunity.estimated_value,
                Opportunity.probability,
                Opportunity.created_at,
                Opportunity.closed_at,
            )
        ).all(),
        columns=[
            "opportunity_id",
            "company_id",
            "stage",
            "value",
            "probability",
            "created_at",
            "closed_at",
        ],
    )
    if not opportunities.empty:
        opportunities["value"] = opportunities["value"].astype(float)
    meetings = pd.DataFrame(
        session.execute(
            select(Meeting.id, Meeting.company_id, Meeting.scheduled_at, Meeting.status)
        ).all(),
        columns=["meeting_id", "company_id", "scheduled_at", "status"],
    )
    # Only companies in the population (excludes merged duplicates' leftovers).
    ids = set(companies["company_id"]) if not companies.empty else set()
    activities = activities[activities["company_id"].isin(ids)]
    opportunities = opportunities[opportunities["company_id"].isin(ids)]
    meetings = meetings[meetings["company_id"].isin(ids)]
    return AnalyticsFrames(companies, activities, opportunities, meetings)


def _company_set(df: pd.DataFrame, mask: pd.Series | None = None) -> set[int]:
    if df.empty:
        return set()
    sel = df if mask is None else df[mask]
    return set(sel["company_id"].astype(int))


def compute_kpis(f: AnalyticsFrames, now: datetime | None = None) -> KPIs:
    now = now or datetime.now(UTC)
    c, a, o, m = f.companies, f.activities, f.opportunities, f.meetings
    active = c[c["archived_at"].isna()] if not c.empty else c

    qualified = (
        _company_set(c, c["highest_stage_order"] >= ProspectStage.QUALIFIED.order)
        if not c.empty
        else set()
    )
    contacted = _company_set(a, a["activity_type"].isin(OUTBOUND_TYPES)) if not a.empty else set()
    replied = (
        _company_set(a, a["activity_type"] == ActivityType.REPLY_RECEIVED.value)
        if not a.empty
        else set()
    ) & contacted
    valid_meetings = m[m["status"].isin(VALID_MEETING_STATUSES)] if not m.empty else m
    with_meeting = _company_set(valid_meetings)
    with_opp = _company_set(o)

    open_o = o[o["stage"].isin(OPEN_OPP_STAGES)] if not o.empty else o
    won_o = o[o["stage"] == "won"] if not o.empty else o
    lost_o = o[o["stage"] == "lost"] if not o.empty else o

    scores = active["lead_score"].dropna() if not active.empty else pd.Series(dtype=float)

    end_of_today = datetime.combine(now.date(), time.max, tzinfo=UTC)
    start_of_today = datetime.combine(now.date(), time.min, tzinfo=UTC)
    if not a.empty:
        pending = a[a["follow_up_at"].notna() & ~a["follow_up_done"].astype(bool)]
        pending = pending[pending["company_id"].isin(set(active["company_id"]))]
        due_ts = pd.to_datetime(pending["follow_up_at"], utc=True)
        due = int((due_ts <= end_of_today).sum())
        overdue = int((due_ts < start_of_today).sum())
    else:
        due = overdue = 0

    weighted = (
        float((open_o["value"] * open_o["probability"] / 100).sum()) if not open_o.empty else 0.0
    )
    return KPIs(
        companies=len(active),
        qualified=len(qualified),
        contacted=len(contacted),
        replied=len(replied),
        companies_with_meeting=len(with_meeting),
        meetings_total=len(valid_meetings),
        open_opportunities=len(open_o),
        won_opportunities=len(won_o),
        lost_opportunities=len(lost_o),
        response_rate=safe_rate(len(replied), len(contacted)),
        meeting_rate=safe_rate(len(with_meeting & contacted), len(contacted)),
        lead_to_opportunity=safe_rate(len(with_opp & qualified), len(qualified)),
        win_rate=safe_rate(len(won_o), len(won_o) + len(lost_o)),
        pipeline_value=round(float(open_o["value"].sum()) if not open_o.empty else 0.0, 2),
        weighted_pipeline_value=round(weighted, 2),
        won_value=round(float(won_o["value"].sum()) if not won_o.empty else 0.0, 2),
        average_lead_score=round(float(scores.mean()), 1) if len(scores) else None,
        follow_ups_due=due,
        follow_ups_overdue=overdue,
    )


# --------------------------------------------------------------------------- chart data
def funnel(f: AnalyticsFrames) -> pd.DataFrame:
    k = compute_kpis(f)
    c = f.companies
    won_companies = (
        _company_set(f.opportunities, f.opportunities["stage"] == "won")
        if not f.opportunities.empty
        else set()
    )
    with_opp = _company_set(f.opportunities)
    return pd.DataFrame(
        {
            "step": [
                "All prospects",
                "Qualified",
                "Contacted",
                "Replied",
                "Meeting",
                "Opportunity",
                "Won",
            ],
            "companies": [
                len(c),
                k.qualified,
                k.contacted,
                k.replied,
                k.companies_with_meeting,
                len(with_opp),
                len(won_companies),
            ],
        }
    )


def _industry_label(value: object) -> str:
    try:
        return Industry(str(value)).label
    except ValueError:
        return "Unknown"


def prospects_by_sector(f: AnalyticsFrames) -> pd.DataFrame:
    c = f.companies[f.companies["archived_at"].isna()]
    if c.empty:
        return pd.DataFrame(columns=["sector", "companies"])
    out = c.assign(sector=c["industry"].map(_industry_label)).groupby("sector").size()
    return out.rename("companies").reset_index().sort_values("companies", ascending=False)


def score_distribution(f: AnalyticsFrames) -> pd.DataFrame:
    c = f.companies[f.companies["archived_at"].isna()]
    return c[["company_name", "lead_score"]].dropna()


def pipeline_by_stage(f: AnalyticsFrames) -> pd.DataFrame:
    c = f.companies
    order = [s.value for s in ProspectStage]
    counts = (
        c.groupby("stage").size().reindex(order, fill_value=0)
        if not c.empty
        else pd.Series(0, index=order)
    )
    return pd.DataFrame(
        {"stage": [ProspectStage(s).label for s in order], "companies": counts.values}
    )


def meetings_over_time(f: AnalyticsFrames) -> pd.DataFrame:
    m = f.meetings
    if m.empty:
        return pd.DataFrame(columns=["month", "status", "meetings"])
    ts = pd.to_datetime(m["scheduled_at"], utc=True)
    out = m.assign(month=ts.dt.tz_localize(None).dt.to_period("M").dt.to_timestamp())
    return out.groupby(["month", "status"]).size().rename("meetings").reset_index()


def monthly_activity(f: AnalyticsFrames) -> pd.DataFrame:
    a = f.activities
    a = a[a["activity_type"] != ActivityType.STAGE_CHANGE.value] if not a.empty else a
    if a.empty:
        return pd.DataFrame(columns=["month", "activity_type", "count"])
    ts = pd.to_datetime(a["occurred_at"], utc=True)
    out = a.assign(month=ts.dt.tz_localize(None).dt.to_period("M").dt.to_timestamp())
    return out.groupby(["month", "activity_type"]).size().rename("count").reset_index()


def conversion_by_sector(f: AnalyticsFrames) -> pd.DataFrame:
    """Per sector: contacted companies, response rate and opportunity rate."""
    c, a = f.companies, f.activities
    if c.empty:
        return pd.DataFrame(columns=["sector", "contacted", "response_rate", "opportunity_rate"])
    contacted = _company_set(a, a["activity_type"].isin(OUTBOUND_TYPES)) if not a.empty else set()
    replied = (
        _company_set(a, a["activity_type"] == ActivityType.REPLY_RECEIVED.value)
        if not a.empty
        else set()
    )
    with_opp = _company_set(f.opportunities)
    rows = []
    for industry, group in c.groupby(c["industry"].fillna("unknown")):
        ids = set(group["company_id"])
        n_contacted = len(ids & contacted)
        rows.append(
            {
                "sector": _industry_label(industry),
                "contacted": n_contacted,
                "response_rate": safe_rate(len(ids & contacted & replied), n_contacted),
                "opportunity_rate": safe_rate(len(ids & contacted & with_opp), n_contacted),
            }
        )
    return pd.DataFrame(rows).sort_values("contacted", ascending=False)


def opportunity_value_by_stage(f: AnalyticsFrames) -> pd.DataFrame:
    o = f.opportunities
    if o.empty:
        return pd.DataFrame(columns=["stage", "value", "weighted_value", "count"])
    o = o.assign(weighted_value=o["value"] * o["probability"] / 100)
    out = o.groupby("stage").agg(
        value=("value", "sum"),
        weighted_value=("weighted_value", "sum"),
        count=("opportunity_id", "count"),
    )
    order = ["open", "proposal_sent", "won", "lost"]
    return out.reindex([s for s in order if s in out.index]).reset_index()


def recent_window(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)
