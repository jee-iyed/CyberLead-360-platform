"""AI outreach: evidence-grounded drafts, editing and human approval. Nothing is sent."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from cyberlead360.database.repositories.companies import CompanyRepository
from cyberlead360.database.repositories.contacts import ContactRepository
from cyberlead360.database.repositories.intelligence import IntelligenceRepository
from cyberlead360.domain.enums import DraftStatus, Language, MessageType, ServiceLine, Tone
from cyberlead360.domain.schemas import OutreachRequest
from cyberlead360.services.compliance_service import ComplianceService
from cyberlead360.services.outreach_service import OutreachService
from cyberlead360.ui.bootstrap import (
    actor,
    db,
    flash,
    llm_provider,
    page_setup,
    run_action,
    settings,
)
from cyberlead360.ui.components import company_selector, dt, empty_state

page_setup("AI Outreach", "✉️")
flash()
st.info(
    "Drafts are suggestions. **CyberLead 360 never sends e-mails or LinkedIn messages.** "
    "Review, edit, approve, send from your own tools, then mark the draft as sent.",
    icon="🧑‍⚖️",
)

with db().session() as s:
    options = CompanyRepository(s).options()
if not options:
    empty_state("No companies yet.")
    st.stop()


def _svc(s):  # type: ignore[no-untyped-def]
    return OutreachService(s, actor(), settings(), llm_provider())


tab_new, tab_drafts = st.tabs(["✨ New draft", "🗂️ Drafts & approval"])

with tab_new:
    cid = company_selector(options, key="outreach_company")
    with db().session() as s:
        compliance = ComplianceService(s, actor())
        contacts = [
            (
                c.id,
                f"{c.full_name} — {c.job_title or 'role unknown'}",
                compliance.suppression_reason(c),
            )
            for c in ContactRepository(s).for_company(cid)
        ]
        n_facts = len(IntelligenceRepository(s).facts_for(cid, ["approved"]))
    allowed = [c for c in contacts if c[2] is None]
    blocked = [c for c in contacts if c[2] is not None]
    if blocked:
        st.caption(
            "Excluded (suppressed / objected / inactive): "
            + ", ".join(c[1].split(" — ")[0] for c in blocked)
        )
    st.caption(f"Grounding: {n_facts} approved fact(s) available for this company.")
    with st.form("generate"):
        c1, c2, c3 = st.columns(3)
        contact_id = c1.selectbox(
            "Recipient",
            [None] + [c[0] for c in allowed],
            format_func=lambda i: (
                "— no specific contact —" if i is None else next(c[1] for c in allowed if c[0] == i)
            ),
        )
        mtype = c2.selectbox(
            "Message type",
            [m.value for m in MessageType],
            format_func=lambda v: MessageType(v).label,
        )
        tone = c3.selectbox("Tone", [t.value for t in Tone])
        c1, c2, c3 = st.columns(3)
        lang = c1.selectbox(
            "Language",
            [lg.value for lg in Language],
            format_func=lambda v: {"en": "English", "fr": "Français"}[v],
        )
        service = c2.selectbox(
            "Service focus",
            [None] + [x.value for x in ServiceLine],
            format_func=lambda v: "Auto (best evidence)" if v is None else ServiceLine(v).label,
        )
        use_llm = c3.toggle(
            "Use LLM",
            value=llm_provider() is not None,
            disabled=llm_provider() is None,
            help="Disabled when no API key is configured (template mode).",
        )
        c1, c2 = st.columns(2)
        sender = c1.text_input("Sender name", "Alex Martin")
        sender_company = c2.text_input("Sender company", "Your Security Firm")
        if st.form_submit_button("Generate draft", type="primary"):
            with st.spinner("Generating…"):
                draft = run_action(
                    lambda s: _svc(s).generate(
                        OutreachRequest(
                            company_id=cid,
                            contact_id=contact_id,
                            message_type=MessageType(mtype),
                            tone=Tone(tone),
                            language=Language(lang),
                            service_focus=ServiceLine(service) if service else None,
                            sender_name=sender,
                            sender_company=sender_company,
                            use_llm=use_llm,
                        )
                    )
                )
            if draft:
                st.session_state["selected_draft_id"] = draft.id
                st.session_state["_flash"] = (
                    f"Draft #{draft.id} created ({draft.generation_mode} mode)."
                )
                st.rerun()

with tab_drafts:
    status_filter = st.multiselect(
        "Status",
        [d.value for d in DraftStatus],
        default=[DraftStatus.DRAFT.value, DraftStatus.APPROVED.value],
    )
    with db().session() as s:
        names = dict(options)
        rows = [
            {
                "id": d.id,
                "company": names.get(d.company_id, f"#{d.company_id}"),
                "type": d.message_type,
                "lang": d.language,
                "tone": d.tone,
                "mode": d.generation_mode,
                "status": d.status,
                "subject": d.subject,
                "created": d.created_at,
            }
            for d in IntelligenceRepository(s).drafts()
            if d.status in status_filter
        ]
    if not rows:
        empty_state("No drafts with this status.")
    else:
        table = pd.DataFrame(rows)
        event = st.dataframe(
            table,
            hide_index=True,
            width="stretch",
            on_select="rerun",
            selection_mode="single-row",
            key="drafts_table",
            column_config={"created": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm")},
        )
        if event.selection.rows:
            st.session_state["selected_draft_id"] = int(table.iloc[event.selection.rows[0]]["id"])

    draft_id = st.session_state.get("selected_draft_id")
    with db().session() as s:
        d = IntelligenceRepository(s).get_draft(draft_id) if draft_id else None
        draft = (
            None
            if d is None
            else {
                "id": d.id,
                "subject": d.subject,
                "body": d.body,
                "status": d.status,
                "warnings": list(d.warnings),
                "evidence": list(d.evidence_fact_ids),
                "mode": d.generation_mode,
                "model": d.model,
                "approved_by": d.approved_by,
                "approved_at": d.approved_at,
                "tokens": (d.input_tokens, d.output_tokens),
                "company": names.get(d.company_id) if rows else None,
            }
        )
    if draft:
        st.divider()
        st.subheader(f"Draft #{draft['id']} · {draft['status']}")
        st.caption(
            f"Mode: {draft['mode']}{' · model ' + draft['model'] if draft['model'] else ''} · "
            "evidence: "
            + (", ".join(f"fact #{i}" for i in draft["evidence"]) or "none (sector-level)")
        )
        for w in draft["warnings"]:
            st.warning(w)
        editable = draft["status"] == DraftStatus.DRAFT.value
        subject = st.text_input("Subject", draft["subject"] or "", disabled=not editable)
        body = st.text_area("Body", draft["body"], height=320, disabled=not editable)
        c1, c2, c3, c4 = st.columns(4)
        if editable and c1.button("Save edits"):
            run_action(
                lambda s: _svc(s).edit(draft["id"], subject, body), "Draft saved.", rerun=True
            )
        if editable and c2.button("Approve", type="primary"):
            run_action(
                lambda s: (_svc(s).edit(draft["id"], subject, body), _svc(s).approve(draft["id"])),
                "Draft approved by you.",
                rerun=True,
            )
        if draft["status"] in (DraftStatus.DRAFT.value, DraftStatus.APPROVED.value) and c3.button(
            "Reject"
        ):
            run_action(lambda s: _svc(s).reject(draft["id"]), "Draft rejected.", rerun=True)
        if draft["status"] == DraftStatus.APPROVED.value:
            st.caption(
                f"Approved by {draft['approved_by']} on {dt(draft['approved_at'], True)}. "
                "Send it yourself, then:"
            )
            if c4.button("Mark as sent manually"):
                run_action(
                    lambda s: _svc(s).mark_sent_manually(draft["id"]),
                    "Recorded as sent; activity logged in the CRM.",
                    rerun=True,
                )
