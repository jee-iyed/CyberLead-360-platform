"""Dashboard: headline KPIs, pipeline summary, follow-ups and recent activity."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import streamlit as st

from cyberlead360.database.repositories.activities import ActivityRepository
from cyberlead360.services import analytics_service as analytics
from cyberlead360.services.scoring_service import ScoringService
from cyberlead360.ui import charts
from cyberlead360.ui.bootstrap import actor, db, page_setup
from cyberlead360.ui.components import empty_state, industry_label, money_compact, pct, stage_label

page_setup("Dashboard", "📊")

with db().session() as s:
    frames = analytics.load_frames(s)
    kpi = analytics.compute_kpis(frames)
    ranking = ScoringService(s, actor()).ranking()
    horizon = datetime.now(UTC) + timedelta(days=7)
    follow_ups = [
        {
            "due": a.follow_up_at,
            "company": name,
            "type": a.activity_type,
            "subject": a.subject,
            "overdue": a.follow_up_at < datetime.now(UTC),
        }
        for a, name in ActivityRepository(s).open_follow_ups(until=horizon)
    ]
    recent = [
        {
            "when": a.occurred_at,
            "company": company,
            "type": a.activity_type,
            "subject": a.subject,
            "contact": contact or "—",
        }
        for a, company, contact in ActivityRepository(s).recent(limit=12)
    ]

if kpi.companies == 0:
    empty_state("No companies yet.", "Load the demo data from the Home page or import a CSV.")
    st.stop()

c = st.columns(6)
c[0].metric("Companies", kpi.companies)
c[1].metric("Qualified", kpi.qualified)
c[2].metric("Contacted", kpi.contacted)
c[3].metric("Replies", kpi.replied)
c[4].metric("Meetings", kpi.meetings_total)
c[5].metric(
    "Avg lead score", kpi.average_lead_score if kpi.average_lead_score is not None else "n/a"
)

c = st.columns(6)
c[0].metric("Response rate", pct(kpi.response_rate), help="Replied ÷ contacted companies")
c[1].metric(
    "Meeting rate", pct(kpi.meeting_rate), help="Contacted companies with a meeting ÷ contacted"
)
c[2].metric("Open opportunities", kpi.open_opportunities)
c[3].metric("Pipeline value", money_compact(kpi.pipeline_value))
c[4].metric(
    "Weighted pipeline",
    money_compact(kpi.weighted_pipeline_value),
    help="Σ value × seller-estimated probability",
)
c[5].metric(
    "Follow-ups due",
    kpi.follow_ups_due,
    delta=f"{kpi.follow_ups_overdue} overdue" if kpi.follow_ups_overdue else None,
    delta_color="inverse",
)

left, right = st.columns(2, gap="large")
with left:
    st.plotly_chart(charts.funnel_chart(analytics.funnel(frames)), width="stretch")
with right:
    stage_df = analytics.pipeline_by_stage(frames)
    st.plotly_chart(
        charts.bar(
            stage_df[stage_df["companies"] > 0],
            "stage",
            "companies",
            "Companies by pipeline stage",
            horizontal=True,
        ),
        width="stretch",
    )

left, right = st.columns(2, gap="large")
with left:
    st.subheader("Follow-ups (next 7 days & overdue)")
    if follow_ups:
        df = pd.DataFrame(follow_ups)
        df["status"] = df.pop("overdue").map({True: "⚠️ overdue", False: "upcoming"})
        st.dataframe(
            df,
            hide_index=True,
            width="stretch",
            column_config={"due": st.column_config.DatetimeColumn("Due", format="YYYY-MM-DD")},
        )
    else:
        st.caption("No follow-ups due. 🎉")
    st.subheader("Top priority prospects")
    if not ranking.empty:
        top = ranking[~ranking["stage"].isin(["won", "lost", "archived"])].head(8)
        st.dataframe(
            top.assign(
                industry=top["industry"].map(industry_label), stage=top["stage"].map(stage_label)
            )[["company", "score", "priority", "industry", "stage", "confidence"]],
            hide_index=True,
            width="stretch",
            column_config={
                "score": st.column_config.ProgressColumn(
                    "Score", min_value=0, max_value=100, format="%d"
                )
            },
        )
with right:
    st.subheader("Recent activity")
    if recent:
        st.dataframe(
            pd.DataFrame(recent),
            hide_index=True,
            width="stretch",
            column_config={
                "when": st.column_config.DatetimeColumn("When", format="YYYY-MM-DD HH:mm")
            },
        )
    else:
        st.caption("No activity recorded yet.")
