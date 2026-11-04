"""Sales pipeline: prospect stages (company lifecycle) and opportunities (deals)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import streamlit as st

from cyberlead360.database.repositories.companies import CompanyFilters, CompanyRepository
from cyberlead360.database.repositories.opportunities import OpportunityRepository
from cyberlead360.domain.enums import OpportunityStage, ProspectStage, ServiceLine
from cyberlead360.domain.pipeline_rules import OPPORTUNITY_TRANSITIONS, allowed_prospect_targets
from cyberlead360.domain.schemas import OpportunityCreate
from cyberlead360.services.pipeline_service import PipelineService
from cyberlead360.ui.bootstrap import actor, db, flash, page_setup, run_action
from cyberlead360.ui.components import company_selector, empty_state, money, stage_label

page_setup("Sales Pipeline", "🧭")
flash()

with db().session() as s:
    repo = CompanyRepository(s)
    options = repo.options()
    board_rows = [
        (c.id, c.company_name, c.prospect_stage) for c, _, _ in repo.search(CompanyFilters())
    ]
if not options:
    empty_state("No companies yet.")
    st.stop()

tab_board, tab_stage, tab_opps = st.tabs(["🗺️ Board", "🔀 Change company stage", "💼 Opportunities"])

with tab_board:
    board = pd.DataFrame(board_rows, columns=["id", "company", "stage"])
    stages = [s for s in ProspectStage if s != ProspectStage.ARCHIVED]
    cols = st.columns(6)
    for i, stage in enumerate(stages):
        subset = board[board["stage"] == stage.value]
        with cols[i % 6].container(border=True):
            st.markdown(f"**{stage.label}** · {len(subset)}")
            for name in subset["company"].head(6):
                st.caption(name)
            if len(subset) > 6:
                st.caption(f"+{len(subset) - 6} more")

with tab_stage:
    cid = company_selector(options, key="pipeline_company")
    with db().session() as s:
        company = CompanyRepository(s).get(cid)
        current = ProspectStage(company.prospect_stage)
    st.write(f"Current stage: **{current.label}**")
    targets = allowed_prospect_targets(current)
    with st.form("stage_change"):
        target = st.selectbox("Move to", [t.value for t in targets], format_func=stage_label)
        note = st.text_input("Note (reason, context)")
        st.caption(
            "Only valid transitions are offered. Proposal / Won follow the opportunity "
            "lifecycle; Archived requires no open deal."
        )
        if st.form_submit_button("Change stage", type="primary"):
            run_action(
                lambda s: PipelineService(s, actor()).change_stage(
                    cid, ProspectStage(target), note
                ),
                "Stage updated and recorded in the activity history.",
                rerun=True,
            )

with tab_opps:
    with db().session() as s:
        opps = [
            {
                "id": o.id,
                "company": name,
                "name": o.name,
                "service": ServiceLine(o.service_line).label,
                "stage": o.stage,
                "value": float(o.estimated_value),
                "currency": o.currency,
                "probability": o.probability,
                "weighted": float(o.estimated_value) * o.probability / 100,
                "close": o.expected_close_date,
                "next action": o.next_action,
                "next date": o.next_action_date,
                "reason": o.won_lost_reason,
            }
            for o, name in OpportunityRepository(s).list()
        ]
    df = pd.DataFrame(opps)
    if not df.empty:
        open_df = df[df["stage"].isin(["open", "proposal_sent"])]
        m = st.columns(4)
        m[0].metric("Open deals", len(open_df))
        m[1].metric("Pipeline", money(open_df["value"].sum()))
        m[2].metric(
            "Weighted",
            money(open_df["weighted"].sum()),
            help="Probability is the seller's forecast, not the lead score.",
        )
        m[3].metric("Won", money(df.loc[df["stage"] == "won", "value"].sum()))
        event = st.dataframe(
            df,
            hide_index=True,
            width="stretch",
            on_select="rerun",
            selection_mode="single-row",
            key="opp_table",
            column_config={
                "value": st.column_config.NumberColumn(format="%.0f"),
                "weighted": st.column_config.NumberColumn(format="%.0f"),
            },
        )
        if event.selection.rows:
            st.session_state["selected_opp_id"] = int(df.iloc[event.selection.rows[0]]["id"])
    else:
        empty_state("No opportunities yet.")

    left, right = st.columns(2, gap="large")
    with left, st.form("new_opp"):
        st.subheader("New opportunity")
        ocid = st.selectbox(
            "Company", [o[0] for o in options], format_func=lambda i: dict(options)[i]
        )
        name = st.text_input("Name *", placeholder="e.g. Annual penetration test 2027")
        service = st.selectbox(
            "Service line",
            [x.value for x in ServiceLine],
            format_func=lambda v: ServiceLine(v).label,
        )
        c1, c2 = st.columns(2)
        value = c1.number_input("Estimated value (EUR)", min_value=0.0, step=1000.0, value=15000.0)
        prob = c2.slider("Probability % (seller forecast)", 0, 100, 20)
        close = st.date_input("Expected close date", value=None)
        next_action = st.text_input("Next action")
        if st.form_submit_button("Create opportunity", type="primary"):
            run_action(
                lambda s: PipelineService(s, actor()).create_opportunity(
                    OpportunityCreate(
                        company_id=ocid,
                        name=name,
                        service_line=ServiceLine(service),
                        estimated_value=Decimal(str(round(value, 2))),
                        probability=prob,
                        expected_close_date=close,
                        next_action=next_action or None,
                    )
                ),
                "Opportunity created; company stage synchronized.",
                rerun=True,
            )

    with right:
        opp_id = st.session_state.get("selected_opp_id")
        opp = next((o for o in opps if o["id"] == opp_id), None)
        if not opp:
            st.caption("Select an opportunity in the table to update it.")
        else:
            st.subheader(f"Update #{opp['id']} · {opp['stage']}")
            current = OpportunityStage(opp["stage"])
            targets = sorted(OPPORTUNITY_TRANSITIONS[current], key=lambda x: x.value)
            if targets:
                with st.form("move_opp"):
                    target = st.selectbox("Move to", [t.value for t in targets])
                    reason = st.text_input("Won / lost reason (required for lost)")
                    if st.form_submit_button("Update stage", type="primary"):
                        run_action(
                            lambda s: PipelineService(s, actor()).move_opportunity(
                                opp["id"], OpportunityStage(target), reason or None
                            ),
                            "Opportunity updated.",
                            rerun=True,
                        )
            if not current.is_closed:
                with st.form("edit_opp"):
                    c1, c2 = st.columns(2)
                    new_val = c1.number_input(
                        "Value", min_value=0.0, value=float(opp["value"]), step=1000.0
                    )
                    new_prob = c2.slider("Probability %", 0, 100, int(opp["probability"]))
                    nxt = st.text_input("Next action", opp["next action"] or "")
                    nxt_date = st.date_input("Next action date", value=opp["next date"])
                    close = st.date_input("Expected close", value=opp["close"])
                    if st.form_submit_button("Save details"):
                        run_action(
                            lambda s: PipelineService(s, actor()).update_opportunity(
                                opp["id"],
                                estimated_value=new_val,
                                probability=new_prob,
                                next_action=nxt or None,
                                next_action_date=nxt_date,
                                expected_close_date=close,
                            ),
                            "Opportunity saved.",
                            rerun=True,
                        )
            if opp["next date"] and opp["next date"] < date.today() and not current.is_closed:
                st.warning("Next action date is in the past.")
