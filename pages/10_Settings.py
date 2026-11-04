"""Settings: scoring rules (versioned), AI provider status, privacy controls, audit log."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from cyberlead360.database.repositories.activities import AuditRepository
from cyberlead360.database.repositories.contacts import SuppressionRepository
from cyberlead360.database.repositories.intelligence import IntelligenceRepository
from cyberlead360.domain.enums import Industry
from cyberlead360.domain.scoring_rules import (
    GeographyRule,
    IndustryRule,
    NeedsRule,
    PriorityThresholds,
    ScoringConfig,
    SizeBand,
    SizeRule,
)
from cyberlead360.services.compliance_service import ComplianceService
from cyberlead360.services.scoring_service import ScoringService
from cyberlead360.ui.bootstrap import (
    actor,
    db,
    flash,
    format_validation_error,
    llm_provider,
    page_setup,
    run_action,
    settings,
)
from cyberlead360.ui.components import dt
from cyberlead360.utils.normalization import COUNTRIES

page_setup("Settings", "⚙️")
flash()

tab_scoring, tab_ai, tab_privacy, tab_audit, tab_app = st.tabs(
    [
        "🎯 Scoring rules",
        "🤖 AI provider",
        "🔒 Privacy & retention",
        "🧾 Audit log",
        "🧩 Application",
    ]
)

# ----------------------------------------------------------------------------- scoring
with tab_scoring:
    with db().session() as s:
        svc = ScoringService(s, actor())
        rule, ruleset = svc.active_ruleset()
        cfg = ruleset.config
        versions = [
            {
                "version": r.version,
                "active": r.is_active,
                "created": r.created_at,
                "by": r.created_by,
                "notes": r.notes,
            }
            for r in IntelligenceRepository(s).rules()
        ]
    st.caption(
        f"Active rules: **v{rule.version}**. Saving creates a new version (history kept); "
        "scores are then recalculated in one controlled operation."
    )
    st.markdown("**Industry fit** (max points)")
    ind_max = st.number_input("Industry max", 0, 100, cfg.industry.max_points, key="ind_max")
    cols = st.columns(4)
    ind_points = {}
    for i, industry in enumerate(Industry):
        ind_points[industry] = cols[i % 4].number_input(
            industry.label,
            0,
            100,
            cfg.industry.points.get(industry, cfg.industry.default_points),
            key=f"ind_{industry.value}",
        )
    st.markdown("**Company size bands**")
    size_max = st.number_input("Size max", 0, 100, cfg.size.max_points, key="size_max")
    bands_df = st.data_editor(
        pd.DataFrame([b.model_dump() for b in cfg.size.bands]),
        num_rows="dynamic",
        width="stretch",
        key="bands",
        column_config={
            "max_employees": st.column_config.NumberColumn(help="empty = no upper bound")
        },
    )
    st.markdown("**Documented cybersecurity need**")
    c = st.columns(5)
    needs_max = c[0].number_input("Needs max", 0, 100, cfg.needs.max_points)
    explicit = c[1].number_input("Explicit sourced need", 0, 100, cfg.needs.explicit_points)
    signal = c[2].number_input("Relevant public signal", 0, 100, cfg.needs.signal_points)
    none_pts = c[3].number_input("No documented need", 0, 100, cfg.needs.none_points)
    verified_only = c[4].checkbox("Verified sources only", cfg.needs.require_verified_source)
    st.markdown("**Geographic fit**")
    c = st.columns(4)
    geo_max = c[0].number_input("Geography max", 0, 100, cfg.geography.max_points)
    prim_pts = c[1].number_input("Primary market points", 0, 100, cfg.geography.primary_points)
    sec_pts = c[2].number_input("Secondary market points", 0, 100, cfg.geography.secondary_points)
    other_pts = c[3].number_input("Other countries points", 0, 100, cfg.geography.other_points)
    c = st.columns(2)
    primary = c[0].multiselect(
        "Primary markets",
        sorted(COUNTRIES),
        cfg.geography.primary_countries,
        format_func=lambda x: f"{COUNTRIES[x]} ({x})",
    )
    secondary = c[1].multiselect(
        "Secondary markets",
        sorted(COUNTRIES),
        cfg.geography.secondary_countries,
        format_func=lambda x: f"{COUNTRIES[x]} ({x})",
    )
    st.markdown("**Priority thresholds**")
    c = st.columns(2)
    high = c[0].number_input("High priority ≥", 0, 100, cfg.priority.high)
    medium = c[1].number_input("Medium priority ≥", 0, 100, cfg.priority.medium)

    new_cfg = None
    try:
        bands = [
            SizeBand(
                min_employees=int(r["min_employees"]),
                max_employees=None if pd.isna(r["max_employees"]) else int(r["max_employees"]),
                points=int(r["points"]),
            )
            for r in bands_df.to_dict("records")
            if not pd.isna(r.get("min_employees"))
        ]
        new_cfg = ScoringConfig(
            industry=IndustryRule(
                max_points=ind_max,
                points=ind_points,
                default_points=min(cfg.industry.default_points, ind_max),
            ),
            size=SizeRule(max_points=size_max, bands=bands),
            needs=NeedsRule(
                max_points=needs_max,
                explicit_points=explicit,
                signal_points=signal,
                none_points=none_pts,
                require_verified_source=verified_only,
            ),
            geography=GeographyRule(
                max_points=geo_max,
                primary_countries=primary,
                secondary_countries=secondary,
                primary_points=prim_pts,
                secondary_points=sec_pts,
                other_points=other_pts,
            ),
            priority=PriorityThresholds(high=high, medium=medium),
        )
    except ValidationError as exc:
        st.error(format_validation_error(exc))
    except (ValueError, TypeError) as exc:
        st.error(f"Invalid configuration: {exc}")

    if new_cfg is not None:
        changed = new_cfg.model_dump(mode="json") != cfg.model_dump(mode="json")
        with db().session() as s:
            impact = ScoringService(s, actor()).impact_preview(new_cfg)
        if changed and len(impact):
            moved = int((impact["before"] != impact["after"]).sum())
            st.info(
                f"Impact preview: {moved} of {len(impact)} active companies would change score · "
                f"mean {impact['before'].mean():.1f} → {impact['after'].mean():.1f}"
            )
        notes = st.text_input("Change notes (why?)")
        confirm = st.checkbox("Publish as a new version and recalculate all active scores")
        if st.button("Publish rules", type="primary", disabled=not (changed and confirm)):

            def _publish(s):  # type: ignore[no-untyped-def]
                svc2 = ScoringService(s, actor())
                new_rule = svc2.publish_rules(new_cfg, notes or None)
                return new_rule.version, svc2.recalculate_all()

            res = run_action(_publish)
            if res:
                st.session_state["_flash"] = (
                    f"Rules v{res[0]} published; {res[1]} scores recalculated."
                )
                st.rerun()
        if not changed:
            st.caption("No changes compared with the active version.")
    with st.expander("Rule version history"):
        st.dataframe(pd.DataFrame(versions), hide_index=True, width="stretch")

# ----------------------------------------------------------------------------- AI
with tab_ai:
    cfg_app = settings()
    st.markdown(
        "The AI provider is configured through **environment variables** (never in the UI or "
        "database, so keys are not stored or displayed):\n\n"
        "```\nLLM_PROVIDER=anthropic            # or openai_compatible, none\n"
        "ANTHROPIC_API_KEY=...\nANTHROPIC_MODEL=claude-opus-5-5\n"
        "# OPENAI_API_KEY=... OPENAI_BASE_URL=... OPENAI_MODEL=...\n"
        "LLM_MAX_OUTPUT_TOKENS=2000\nLLM_TIMEOUT_SECONDS=60\n```"
    )
    st.write(
        f"**Provider:** {cfg_app.llm_provider} · **Model:** {cfg_app.active_model or '—'} · "
        f"**Status:** {'ready' if llm_provider() else 'not configured → template mode'}"
    )
    st.write(
        f"**Budgets:** max output {cfg_app.llm_max_output_tokens} tokens · max input "
        f"{cfg_app.llm_max_input_chars} characters of context · "
        f"timeout {cfg_app.llm_timeout_seconds:g}s"
    )
    if cfg_app.llm_input_price_per_mtok or cfg_app.llm_output_price_per_mtok:
        st.write(
            f"**Configured prices (USD / 1M tokens):** in {cfg_app.llm_input_price_per_mtok} · "
            f"out {cfg_app.llm_output_price_per_mtok}"
        )
    else:
        st.caption(
            "Set LLM_INPUT_PRICE_PER_MTOK / LLM_OUTPUT_PRICE_PER_MTOK to display cost estimates."
        )
    st.caption(
        "Prompts are not logged (only provider, model, latency and token counts). Contact "
        "names, e-mails and phones are never sent; a {{first_name}} placeholder is filled locally."
    )

# ----------------------------------------------------------------------------- privacy
with tab_privacy:
    cfg_app = settings()
    st.subheader("Retention")
    days = st.number_input(
        "Retention period (days since last contact / creation)",
        30,
        3650,
        cfg_app.contact_retention_days,
    )
    with db().session() as s:
        candidates = [
            (c.id, c.company_id, c.last_contacted_at, c.created_at)
            for c in ComplianceService(s, actor()).retention_candidates(int(days))
        ]
    st.write(f"{len(candidates)} contact(s) exceed the retention period.")
    if candidates:
        st.dataframe(
            pd.DataFrame(
                candidates, columns=["contact_id", "company_id", "last_contacted", "created"]
            ),
            hide_index=True,
            width="stretch",
        )
        if st.checkbox("I confirm anonymizing these contacts (irreversible)") and st.button(
            "Apply retention"
        ):
            n = run_action(lambda s: ComplianceService(s, actor()).apply_retention(int(days)))
            if n is not None:
                st.session_state["_flash"] = f"{n} contact(s) anonymized."
                st.rerun()
    st.subheader("Suppression list")
    st.caption(
        "E-mails are stored only as SHA-256 hashes. Domains block outreach to a whole company."
    )
    c1, c2 = st.columns(2)
    with c1, st.form("suppress_email"):
        email = st.text_input("E-mail to suppress")
        reason = st.text_input("Reason", "Objection received")
        if st.form_submit_button("Suppress e-mail") and email.strip():
            run_action(
                lambda s: ComplianceService(s, actor()).suppress_email(email, reason),
                "E-mail suppressed.",
                rerun=True,
            )
    with c2, st.form("suppress_domain"):
        domain = st.text_input("Domain to suppress", placeholder="company.example")
        dreason = st.text_input("Reason ", "Company asked not to be contacted")
        if st.form_submit_button("Suppress domain") and domain.strip():
            run_action(
                lambda s: ComplianceService(s, actor()).suppress_domain(domain, dreason),
                "Domain suppressed.",
                rerun=True,
            )
    with db().session() as s:
        sup = [
            {
                "id": r.id,
                "type": "domain" if r.domain else "e-mail hash",
                "value": r.domain or (r.email_sha256[:12] + "…"),
                "reason": r.reason,
                "created": r.created_at,
                "by": r.created_by,
            }
            for r in SuppressionRepository(s).all()
        ]
    if sup:
        st.dataframe(pd.DataFrame(sup), hide_index=True, width="stretch")

# ----------------------------------------------------------------------------- audit
with tab_audit:
    etype = st.selectbox(
        "Entity",
        [
            None,
            "company",
            "contact",
            "fact",
            "source",
            "opportunity",
            "outreach_draft",
            "scoring_rule",
            "suppression",
            "meeting",
        ],
        format_func=lambda v: "All" if v is None else v,
    )
    with db().session() as s:
        events = [
            {
                "when": e.occurred_at,
                "entity": e.entity_type,
                "id": e.entity_id,
                "action": e.action,
                "actor": e.actor,
                "details": str(e.details),
            }
            for e in AuditRepository(s).recent(300, etype)
        ]
    st.caption("Append-only accountability log. Details never contain personal data values.")
    st.dataframe(
        pd.DataFrame(events),
        hide_index=True,
        width="stretch",
        column_config={"when": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm:ss")},
    )

# ----------------------------------------------------------------------------- app
with tab_app:
    st.dataframe(
        pd.DataFrame(settings().public_summary().items(), columns=["setting", "value"]).astype(str),
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "Change these through environment variables or the `.env` file, then restart. "
        f"Generated {dt(pd.Timestamp.now(tz='UTC').to_pydatetime(), True)}."
    )
