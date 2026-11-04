"""CyberLead 360 — Streamlit entry point (Home).

Run:  uv run streamlit run app.py
Pages in ``pages/`` are registered below with ``st.navigation`` (grouped sidebar).
"""

from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st
from sqlalchemy import func, select

from cyberlead360.database.models import Company
from cyberlead360.ui.bootstrap import db, flash, llm_provider, page_setup, settings


def home() -> None:
    page_setup("CyberLead 360", "🛡️")
    st.caption("AI-Powered Cybersecurity B2B Sales Intelligence & Prospect Management Platform")
    flash()

    with db().session() as s:
        n_companies = s.scalar(select(func.count(Company.id))) or 0

    left, right = st.columns([3, 2], gap="large")
    with left:
        st.markdown(
            """
    CyberLead 360 helps cybersecurity service providers **find, qualify and engage** B2B
    prospects with traceable evidence:

    1. **Companies**: import, validate, deduplicate and manage target accounts.
    2. **Company Intelligence**: record public facts *with their sources*, review them.
    3. **Lead Qualification**: transparent, rule-based scoring with explanations.
    4. **AI Outreach**: evidence-grounded drafts (LLM or template), human-approved.
    5. **Pipeline & Activities**: stages, opportunities, interactions, follow-ups.
    6. **Analytics**: conversion metrics with explicit denominators.
            """
        )
        st.info(
            "A lead score measures **commercial fit** from documented evidence. It is not a "
            "probability of conversion and never a judgement about a company's security posture.",
            icon="ℹ️",
        )
    with right:
        with st.container(border=True):
            st.subheader("System status")
            cfg = settings()
            st.write(f"**Database:** {'SQLite (local)' if cfg.is_sqlite else 'PostgreSQL'}")
            st.write(f"**Companies:** {n_companies}")
            st.write(
                "**AI mode:** "
                + (
                    f"LLM ({cfg.llm_provider}, `{cfg.active_model}`)"
                    if llm_provider()
                    else "deterministic templates (no API key configured)"
                )
            )
            st.write(f"**Web retrieval:** {'enabled' if cfg.enable_web_retrieval else 'disabled'}")
            st.caption("Single-operator demonstrator — no authentication. Do not expose publicly.")

        if n_companies == 0:
            with st.container(border=True):
                st.subheader("Get started")
                st.write(
                    "The database is empty. Load the fictional demonstration dataset "
                    "(≈80 companies with contacts, sourced facts, activities and deals)."
                )
                if st.button("Load fictional demo data", type="primary"):
                    from cyberlead360.demo_seed import seed

                    with st.spinner("Generating demo data…"):
                        stats = seed(db(), datetime.now(UTC).date())
                    st.session_state["_flash"] = (
                        f"Demo data loaded: {stats['companies']} companies, "
                        f"{stats['contacts']} contacts, {stats['facts']} facts."
                    )
                    st.rerun()
                st.caption("Or import your own CSV in **Companies → Import CSV**.")
        else:
            st.page_link("pages/1_Dashboard.py", label="Open the dashboard →", icon="📊")


navigation = st.navigation(
    {
        "Overview": [
            st.Page(home, title="Home", icon="🛡️", default=True),
            st.Page("pages/1_Dashboard.py", title="Dashboard", icon="📊"),
            st.Page("pages/9_Analytics.py", title="Analytics", icon="📈"),
        ],
        "Prospects": [
            st.Page("pages/2_Companies.py", title="Companies", icon="🏢"),
            st.Page("pages/3_Contacts.py", title="Contacts", icon="👥"),
            st.Page("pages/4_Lead_Qualification.py", title="Lead Qualification", icon="🎯"),
            st.Page("pages/5_Company_Intelligence.py", title="Company Intelligence", icon="🔬"),
        ],
        "Engagement": [
            st.Page("pages/6_AI_Outreach.py", title="AI Outreach", icon="✉️"),
            st.Page("pages/7_Sales_Pipeline.py", title="Sales Pipeline", icon="🧭"),
            st.Page("pages/8_Activities.py", title="Activities", icon="🗓️"),
        ],
        "Administration": [st.Page("pages/10_Settings.py", title="Settings", icon="⚙️")],
    }
)
navigation.run()
