"""Sales analytics: KPIs with documented denominators, charts and data exports."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from cyberlead360.services import analytics_service as analytics
from cyberlead360.services.export_service import ExportService, to_safe_csv
from cyberlead360.ui import charts
from cyberlead360.ui.bootstrap import actor, db, page_setup
from cyberlead360.ui.components import empty_state, money_compact, pct

page_setup("Analytics", "📈")

with db().session() as s:
    frames = analytics.load_frames(s)
if frames.companies.empty:
    empty_state("No data to analyse yet.")
    st.stop()
k = analytics.compute_kpis(frames)

m = st.columns(5)
m[0].metric(
    "Response rate",
    pct(k.response_rate),
    help=f"{k.replied} replied ÷ {k.contacted} contacted companies",
)
m[1].metric(
    "Meeting rate",
    pct(k.meeting_rate),
    help="Contacted companies with a meeting ÷ contacted companies",
)
m[2].metric(
    "Lead → opportunity",
    pct(k.lead_to_opportunity),
    help="Qualified companies with ≥1 opportunity ÷ qualified companies",
)
m[3].metric(
    "Win rate",
    pct(k.win_rate),
    help=f"{k.won_opportunities} won ÷ "
    f"{k.won_opportunities + k.lost_opportunities} closed opportunities",
)
m[4].metric("Won value", money_compact(k.won_value))
m = st.columns(5)
m[0].metric("Open opportunities", k.open_opportunities)
m[1].metric("Won", k.won_opportunities)
m[2].metric("Lost", k.lost_opportunities)
m[3].metric("Pipeline", money_compact(k.pipeline_value))
m[4].metric("Weighted pipeline", money_compact(k.weighted_pipeline_value))

c1, c2 = st.columns(2, gap="large")
c1.plotly_chart(charts.funnel_chart(analytics.funnel(frames)), width="stretch")
c2.plotly_chart(
    charts.bar(
        analytics.prospects_by_sector(frames),
        "sector",
        "companies",
        "Active prospects by sector",
        horizontal=True,
    ),
    width="stretch",
)

c1, c2 = st.columns(2, gap="large")
c1.plotly_chart(
    charts.histogram(analytics.score_distribution(frames), "lead_score", "Lead score distribution"),
    width="stretch",
)
stage_df = analytics.pipeline_by_stage(frames)
c2.plotly_chart(charts.bar(stage_df, "stage", "companies", "Pipeline by stage"), width="stretch")

c1, c2 = st.columns(2, gap="large")
meet = analytics.meetings_over_time(frames)
if meet.empty:
    c1.caption("No meetings yet.")
else:
    c1.plotly_chart(
        charts.stacked_time(meet, "month", "meetings", "status", "Meetings over time"),
        width="stretch",
    )
act = analytics.monthly_activity(frames)
if act.empty:
    c2.caption("No activity yet.")
else:
    c2.plotly_chart(
        charts.stacked_time(act, "month", "count", "activity_type", "Monthly activity"),
        width="stretch",
    )

c1, c2 = st.columns(2, gap="large")
conv = analytics.conversion_by_sector(frames)
conv_plot = conv[conv["contacted"] > 0].copy()
if conv_plot.empty:
    c1.caption("No contacted companies yet.")
else:
    long = conv_plot.melt(
        id_vars=["sector", "contacted"],
        value_vars=["response_rate", "opportunity_rate"],
        var_name="metric",
        value_name="rate",
    ).dropna()
    fig = charts.bar(
        long,
        "sector",
        "rate",
        "Conversion by sector (of contacted companies)",
        color="metric",
        text_auto=".0%",
    )
    fig.update_layout(barmode="group", yaxis_tickformat=".0%")
    c1.plotly_chart(fig, width="stretch")
val = analytics.opportunity_value_by_stage(frames)
if val.empty:
    c2.caption("No opportunities yet.")
else:
    long_v = val.melt(
        id_vars=["stage"],
        value_vars=["value", "weighted_value"],
        var_name="measure",
        value_name="eur",
    )
    fig = charts.bar(
        long_v,
        "stage",
        "eur",
        "Opportunity value by stage (EUR)",
        color="measure",
        text_auto=".2s",
    )
    fig.update_layout(barmode="group")
    c2.plotly_chart(fig, width="stretch")

with st.expander("📐 Metric definitions"):
    st.markdown(analytics.__doc__ or "")
    st.dataframe(conv, hide_index=True, width="stretch")

st.subheader("Exports")
with db().session() as s:
    exp = ExportService(s, actor())
    datasets = {
        "opportunities": exp.opportunities(),
        "activities": exp.activities(),
        "kpis": pd.DataFrame([k.as_dict()]),
    }
cols = st.columns(len(datasets))
for col, (name, df) in zip(cols, datasets.items(), strict=True):
    col.download_button(
        f"{name}.csv ({len(df)} rows)",
        to_safe_csv(df),
        file_name=f"cyberlead360_{name}.csv",
        mime="text/csv",
    )
