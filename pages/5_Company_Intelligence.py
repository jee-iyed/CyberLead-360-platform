"""Company intelligence: sourced facts, freshness, human review, AI summary & analysis."""

from __future__ import annotations

from datetime import UTC, datetime, time

import pandas as pd
import streamlit as st

from cyberlead360.database.repositories.companies import CompanyRepository
from cyberlead360.database.repositories.intelligence import IntelligenceRepository
from cyberlead360.domain.enums import (
    Confidence,
    FactType,
    ReviewStatus,
    SourceType,
    VerificationStatus,
)
from cyberlead360.domain.schemas import FactCreate, SourceCreate
from cyberlead360.services.ai_service import AIService, build_context
from cyberlead360.services.enrichment_service import EnrichmentService
from cyberlead360.ui.bootstrap import (
    actor,
    db,
    flash,
    llm_provider,
    page_setup,
    run_action,
    settings,
)
from cyberlead360.ui.components import company_selector, dt, empty_state, md, safe_link

page_setup("Company Intelligence", "🔬")
flash()
st.caption(
    "Every fact must reference a real, recorded source. Only **approved** facts are used "
    "for scoring and AI generation. No vulnerability scanning or intrusive reconnaissance."
)

with db().session() as s:
    options = CompanyRepository(s).options()
if not options:
    empty_state("No companies yet.")
    st.stop()
cid = company_selector(options, key="intel_company")

with db().session() as s:
    facts_df = EnrichmentService(s, actor()).facts_dataframe(cid, settings().fact_freshness_days)
    sources = [
        {
            "id": src.id,
            "title": src.title,
            "type": src.source_type,
            "url": src.url,
            "verification": src.verification_status,
            "published": src.published_at,
            "collected": src.collected_at,
            "by": src.collected_by,
        }
        for src in IntelligenceRepository(s).sources_for(cid)
    ]
    company = CompanyRepository(s).get(cid)
    website = company.website if company else None

tab_facts, tab_review, tab_add, tab_sources, tab_ai = st.tabs(
    [
        "📚 Facts",
        "✅ Review queue",
        "➕ Add source / fact",
        "🔗 Sources",
        "🤖 AI summary & analysis",
    ]
)

with tab_facts:
    if facts_df.empty:
        empty_state(
            "No facts recorded for this company.",
            "Add a source and a fact, or retrieve the official website (if enabled).",
        )
    else:
        m = st.columns(4)
        m[0].metric("Facts", len(facts_df))
        m[1].metric("Approved", int((facts_df["review"] == "approved").sum()))
        m[2].metric("Pending review", int((facts_df["review"] == "pending").sum()))
        m[3].metric("Stale (> threshold)", int((facts_df["freshness"] == "stale").sum()))
        st.dataframe(
            facts_df,
            hide_index=True,
            width="stretch",
            column_config={
                "url": st.column_config.LinkColumn("Source link"),
                "observed": st.column_config.DatetimeColumn(format="YYYY-MM-DD"),
                "collected": st.column_config.DatetimeColumn(format="YYYY-MM-DD"),
                "statement": st.column_config.TextColumn(width="large"),
            },
        )
        st.caption(
            f"Freshness: fresh ≤ {settings().fact_freshness_days // 2} days · ageing ≤ "
            f"{settings().fact_freshness_days} days · stale beyond."
        )

with tab_review:
    pending = facts_df[facts_df["review"] == "pending"] if not facts_df.empty else facts_df
    if pending.empty:
        st.success("No facts awaiting review.")
    for _, row in pending.iterrows():
        with st.container(border=True):
            st.markdown(
                f"**Fact #{row['fact_id']}** · {md(row['type'])} · source: {md(row['source'])} "
                f"({row['source_verification']})"
            )
            st.text(row["statement"])  # rendered as plain text (untrusted)
            safe_link("Open source", row["url"])
            c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
            new_type = c1.selectbox(
                "Classify as",
                [f.value for f in FactType],
                format_func=lambda v: FactType(v).label,
                key=f"t{row['fact_id']}",
                index=[f.label for f in FactType].index(row["type"]),
            )
            new_conf = c2.selectbox(
                "Confidence",
                [c.value for c in Confidence],
                index=[c.value for c in Confidence].index(row["confidence"]),
                key=f"c{row['fact_id']}",
            )
            fid = int(row["fact_id"])
            if c3.button("Approve", key=f"a{fid}", type="primary"):
                run_action(
                    lambda s, f=fid, t=new_type, c=new_conf: EnrichmentService(
                        s, actor()
                    ).review_fact(
                        f, ReviewStatus.APPROVED, fact_type=FactType(t), confidence=Confidence(c)
                    ),
                    f"Fact #{fid} approved; score updated.",
                    rerun=True,
                )
            if c4.button("Reject", key=f"r{fid}"):
                run_action(
                    lambda s, f=fid: EnrichmentService(s, actor()).review_fact(
                        f, ReviewStatus.REJECTED
                    ),
                    f"Fact #{fid} rejected.",
                    rerun=True,
                )

with tab_add:
    left, right = st.columns(2, gap="large")
    with left, st.form("add_source"):
        st.subheader("1 · Record a source")
        stype = st.selectbox(
            "Source type", [t.value for t in SourceType if t != SourceType.DEMO_FICTIONAL]
        )
        title = st.text_input("Title *", placeholder="e.g. Press release: new production site")
        url = st.text_input("URL (required for public web sources)")
        publisher = st.text_input("Publisher")
        published = st.date_input("Publication / observation date", value=None)
        notes = st.text_area("Notes")
        if st.form_submit_button("Save source", type="primary"):
            run_action(
                lambda s: EnrichmentService(s, actor()).add_source(
                    SourceCreate(
                        company_id=cid,
                        source_type=SourceType(stype),
                        title=title,
                        url=url or None,
                        publisher=publisher or None,
                        notes=notes or None,
                        published_at=datetime.combine(published, time(12), tzinfo=UTC)
                        if published
                        else None,
                    )
                ),
                "Source saved.",
                rerun=True,
            )
    with right:
        st.subheader("2 · Record a fact from that source")
        if not sources:
            st.info("Record a source first — facts without a source are not allowed.")
        else:
            with st.form("add_fact"):
                source_id = st.selectbox(
                    "Source *",
                    [x["id"] for x in sources],
                    format_func=lambda i: next(x["title"] for x in sources if x["id"] == i),
                )
                ftype = st.selectbox(
                    "Fact type",
                    [f.value for f in FactType],
                    format_func=lambda v: FactType(v).label,
                )
                statement = st.text_area("Statement * (factual, as published — no speculation)")
                excerpt = st.text_area("Supporting excerpt (optional)")
                conf = st.selectbox("Confidence", [c.value for c in Confidence], index=1)
                approve = st.checkbox("I have reviewed this fact against its source (approve now)")
                if st.form_submit_button("Save fact", type="primary"):
                    run_action(
                        lambda s: EnrichmentService(s, actor()).add_fact(
                            FactCreate(
                                company_id=cid,
                                source_id=source_id,
                                fact_type=FactType(ftype),
                                statement=statement,
                                excerpt=excerpt or None,
                                confidence=Confidence(conf),
                            ),
                            approve=approve,
                        ),
                        "Fact saved.",
                        rerun=True,
                    )
    st.divider()
    st.subheader("Retrieve the official website (optional)")
    cfg = settings()
    if not cfg.enable_web_retrieval:
        st.caption(
            "Disabled. Set `ENABLE_WEB_RETRIEVAL=true` to allow fetching the company's own "
            "public website (SSRF-protected, robots.txt respected, rate-limited, size-capped). "
            "Extracted text becomes *pending* facts for human review."
        )
    else:
        st.caption(
            f"Target: {website or '— no website —'} · User-Agent: {cfg.retrieval_user_agent}"
        )
        if st.button("Retrieve website", disabled=not website):
            res = run_action(
                lambda s: EnrichmentService(s, actor()).retrieve_official_website(cid, cfg)
            )
            if res:
                st.session_state["_flash"] = (
                    f"Retrieved; {len(res[1])} candidate facts await review."
                )
                st.rerun()

with tab_sources:
    if not sources:
        empty_state("No sources recorded.")
    for src in sources:
        with st.container(border=True):
            st.markdown(f"**#{src['id']} · {md(src['title'])}**")
            st.caption(
                f"{src['type']} · published {dt(src['published'])} · collected "
                f"{dt(src['collected'])} by {src['by'] or '—'} · "
                f"verification: **{src['verification']}**"
            )
            c1, c2, c3 = st.columns([1, 1, 3])
            if src["url"]:
                with c3:
                    safe_link("Open original", src["url"])
            for col, status in (
                (c1, VerificationStatus.VERIFIED),
                (c2, VerificationStatus.REJECTED),
            ):
                if src["verification"] != status.value and col.button(
                    status.value.capitalize(), key=f"v{src['id']}{status.value}"
                ):
                    run_action(
                        lambda s, i=src["id"], st_=status: EnrichmentService(
                            s, actor()
                        ).set_source_verification(i, st_),
                        "Source updated.",
                        rerun=True,
                    )

with tab_ai:
    provider = llm_provider()
    use_llm = st.toggle(
        "Use configured LLM",
        value=provider is not None,
        disabled=provider is None,
        help="Without an API key, deterministic template logic is used.",
    )
    st.caption(
        "Input: approved facts only (sanitized and delimited as untrusted data). "
        "Output validated with Pydantic and checked for unsupported risk claims."
    )
    c1, c2 = st.columns(2)
    if c1.button("Generate company summary", type="primary"):
        with db().session() as s, st.spinner("Generating…"):
            ctx = build_context(s, cid)
            st.session_state["intel_summary"] = AIService(settings(), provider).summarize(
                ctx, use_llm
            )
    if c2.button("Analyse service alignment"):
        with db().session() as s, st.spinner("Analysing…"):
            ctx = build_context(s, cid)
            st.session_state["intel_analysis"] = AIService(settings(), provider).analyze(
                ctx, use_llm
            )

    if "intel_summary" in st.session_state:
        out, meta = st.session_state["intel_summary"]
        with st.container(border=True):
            st.markdown(f"#### Summary · _{meta.mode.value}_ mode")
            st.text(out.profile)
            if out.business_context:
                st.markdown("**Business context**")
                for line in out.business_context:
                    st.text("• " + line)
            if out.possible_service_alignment:
                st.markdown("**Possible service alignment**")
                for line in out.possible_service_alignment:
                    st.text("• " + line)
            if out.unknowns:
                st.markdown("**Unknown / uncertain**")
                st.text("\n".join("• " + u for u in out.unknowns))
            if out.evidence:
                st.caption("Evidence: " + ", ".join(f"fact #{e.fact_id}" for e in out.evidence))
            for w in meta.warnings:
                st.warning(w)
            if meta.input_tokens is not None:
                cost = (
                    f"${meta.estimated_cost_usd:.4f}"
                    if meta.estimated_cost_usd is not None
                    else "prices not configured"
                )
                st.caption(
                    f"Tokens in/out: {meta.input_tokens}/{meta.output_tokens} · est. cost: {cost}"
                )
    if "intel_analysis" in st.session_state:
        out, meta = st.session_state["intel_analysis"]
        with st.container(border=True):
            st.markdown(f"#### Service alignment · _{meta.mode.value}_ mode")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "service": s.service_line.label,
                            "strength": s.strength.value,
                            "rationale": s.rationale,
                            "facts": ", ".join(f"#{i}" for i in s.evidence_fact_ids) or "—",
                        }
                        for s in out.suggestions
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
            for c in out.caveats:
                st.caption("⚠️ " + c)
            for w in meta.warnings:
                st.warning(w)
