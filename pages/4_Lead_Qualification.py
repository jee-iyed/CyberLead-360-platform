"""Lead qualification: ranking, explainable breakdowns, completeness, history."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from cyberlead360.database.repositories.intelligence import IntelligenceRepository
from cyberlead360.services.scoring_service import ScoringService
from cyberlead360.ui.bootstrap import actor, db, flash, page_setup, run_action
from cyberlead360.ui.components import dt, empty_state, industry_label, priority_pill, stage_label
from cyberlead360.ui.theme import AMBER, BLUE, GREEN, RED, SLATE

page_setup("Lead Qualification", "🎯")
flash()
st.caption(
    "Rule-based, deterministic and explainable. The score measures commercial fit from "
    "documented evidence — it is **not** a probability of conversion and **not** a "
    "security risk rating. Configure rules in **Settings**."
)

with db().session() as s:
    svc = ScoringService(s, actor())
    rule, _ = svc.active_ruleset()
    rule_version = rule.version
    ranking = svc.ranking()
    stale = svc.stale_count()

if stale:
    st.warning(f"{stale} companies were scored with an older rule version than v{rule_version}.")
    if st.button("Recalculate all scores with the active rules"):
        n = run_action(lambda s: ScoringService(s, actor()).recalculate_all())
        if n is not None:
            st.session_state["_flash"] = f"Recalculated {n} scores."
            st.rerun()

if ranking.empty:
    empty_state("No scored companies yet.")
    st.stop()

f1, f2, f3 = st.columns(3)
prio = f1.multiselect("Priority", ["high", "medium", "low"], default=["high", "medium", "low"])
conf = f2.multiselect(
    "Evidence confidence", ["high", "medium", "low"], default=["high", "medium", "low"]
)
hide_closed = f3.checkbox("Hide won / lost / archived", value=True)
view = ranking[ranking["priority"].isin(prio) & ranking["confidence"].isin(conf)]
if hide_closed:
    view = view[~view["stage"].isin(["won", "lost", "archived"])]
view = view.assign(
    industry=view["industry"].map(industry_label), stage=view["stage"].map(stage_label)
)

m = st.columns(4)
m[0].metric("Ranked companies", len(view))
m[1].metric("High priority", int((view["priority"] == "high").sum()))
m[2].metric(
    "Average completeness", f"{view['completeness'].mean() * 100:.0f}%" if len(view) else "n/a"
)
m[3].metric("Active rules", f"v{rule_version}")

event = st.dataframe(
    view[
        [
            "id",
            "company",
            "score",
            "priority",
            "completeness",
            "confidence",
            "industry",
            "country",
            "employees",
            "stage",
            "rules_version",
        ]
    ],
    hide_index=True,
    width="stretch",
    on_select="rerun",
    selection_mode="single-row",
    key="ranking_table",
    column_config={
        "score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
        "completeness": st.column_config.ProgressColumn(
            "Data completeness", min_value=0, max_value=1, format="percent"
        ),
        "rules_version": st.column_config.NumberColumn("Rules v"),
    },
)
if event.selection.rows:
    st.session_state["selected_company_id"] = int(view.iloc[event.selection.rows[0]]["id"])

cid = st.session_state.get("selected_company_id")
if cid not in set(ranking["id"]):
    cid = int(view.iloc[0]["id"]) if len(view) else int(ranking.iloc[0]["id"])

with db().session() as s:
    repo = IntelligenceRepository(s)
    current = repo.current_score(cid)
    history = [(r.calculated_at, r.total_score, r.rules_version) for r in repo.score_history(cid)]
    name = ranking.loc[ranking["id"] == cid, "company"].iloc[0]
    snapshot = {
        "score": current.total_score,
        "priority": current.priority,
        "breakdown": current.breakdown,
        "missing": current.missing_information,
        "explanation": current.explanation,
        "completeness": current.data_completeness,
        "confidence": current.evidence_confidence,
        "version": current.rules_version,
        "at": current.calculated_at,
    }

st.divider()
st.subheader(f"Score explanation — {name}")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Lead score", f"{snapshot['score']}/100")
c2.markdown("**Priority**<br>" + priority_pill(snapshot["priority"]), unsafe_allow_html=True)
c3.metric("Data completeness", f"{snapshot['completeness'] * 100:.0f}%")
c4.metric("Evidence confidence", snapshot["confidence"])
st.write(snapshot["explanation"])
st.caption(f"Calculated {dt(snapshot['at'], True)} with rules v{snapshot['version']}.")

status_color = {
    "matched": GREEN,
    "partial": BLUE,
    "no_match": SLATE,
    "no_evidence": AMBER,
    "missing": RED,
}
bd = pd.DataFrame(snapshot["breakdown"])
fig = go.Figure()
fig.add_bar(
    y=bd["label"],
    x=bd["max_points"],
    orientation="h",
    name="Maximum",
    marker_color="#E2E8F0",
    hoverinfo="skip",
)
fig.add_bar(
    y=bd["label"],
    x=bd["points"],
    orientation="h",
    name="Points",
    marker_color=[status_color[s] for s in bd["status"]],
    text=[f"{p}/{mx}" for p, mx in zip(bd["points"], bd["max_points"], strict=True)],
    textposition="inside",
)
fig.update_layout(
    barmode="overlay",
    height=260,
    margin=dict(l=10, r=10, t=10, b=10),
    showlegend=False,
    plot_bgcolor="white",
)
st.plotly_chart(fig, width="stretch")

st.dataframe(
    bd.assign(
        evidence=bd["evidence_fact_ids"].map(lambda ids: ", ".join(f"#{i}" for i in ids) or "—")
    )[["label", "points", "max_points", "status", "reason", "evidence"]],
    hide_index=True,
    width="stretch",
)
st.caption(
    "Status legend — matched: full fit · partial: some fit · no_match: known, does not fit · "
    "no_evidence: facts reviewed, none shows a need · **missing: unknown (not negative)**."
)
if snapshot["missing"]:
    st.warning("Missing information: " + "; ".join(snapshot["missing"]))

c1, c2 = st.columns([1, 2])
with c1:
    if st.button("Recalculate this company"):
        run_action(
            lambda s: ScoringService(s, actor()).score_company(cid),
            "Score recalculated.",
            rerun=True,
        )
with c2:
    if len(history) > 1:
        with st.expander(f"Score history ({len(history)} calculations)"):
            st.dataframe(
                pd.DataFrame(history, columns=["calculated_at", "score", "rules_version"]),
                hide_index=True,
                width="stretch",
            )
