"""Contacts: professional contacts linked to companies, with privacy workflows."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from cyberlead360.database.repositories.activities import ActivityRepository
from cyberlead360.database.repositories.companies import CompanyRepository
from cyberlead360.database.repositories.contacts import ContactRepository
from cyberlead360.database.repositories.intelligence import IntelligenceRepository
from cyberlead360.domain.enums import ContactStatus
from cyberlead360.domain.schemas import ContactCreate, ContactUpdate
from cyberlead360.services.compliance_service import ComplianceService
from cyberlead360.services.contact_service import ContactService
from cyberlead360.services.export_service import ExportService, to_safe_csv
from cyberlead360.ui.bootstrap import actor, db, flash, page_setup, run_action
from cyberlead360.ui.components import company_selector, dt, empty_state

page_setup("Contacts", "👥")
flash()
st.caption(
    "🔒 Personal data. Only professional contact details from legitimate sources. "
    "Objections and suppression are enforced before any outreach."
)

with db().session() as s:
    company_options = CompanyRepository(s).options()

tab_list, tab_add, tab_manage, tab_export = st.tabs(
    ["📇 Contacts", "➕ Add contact", "🛠️ Manage selected", "📤 Export"]
)

with tab_list:
    f1, f2, f3 = st.columns([2, 2, 2])
    text = f1.text_input("Search name, title or company")
    company_filter = f2.selectbox(
        "Company",
        [None] + [o[0] for o in company_options],
        format_func=lambda i: "All" if i is None else dict(company_options)[i],
    )
    statuses = f3.multiselect("Status", [c.value for c in ContactStatus])
    with db().session() as s:
        rows = ContactRepository(s).search(text or None, company_filter, statuses or None)
        compliance = ComplianceService(s, actor())
        table = pd.DataFrame(
            [
                {
                    "id": c.id,
                    "name": c.full_name,
                    "company": company,
                    "title": c.job_title,
                    "email": c.professional_email,
                    "status": c.contact_status,
                    "objection": c.objection_status,
                    "contactable": compliance.suppression_reason(c) is None,
                    "last contacted": c.last_contacted_at,
                    "owner": c.owner,
                }
                for c, company in rows
            ]
        )
    if table.empty:
        empty_state("No contacts match.", "Add contacts from the 'Add contact' tab.")
    else:
        st.caption(f"{len(table)} contacts · select a row to manage it")
        event = st.dataframe(
            table,
            hide_index=True,
            width="stretch",
            on_select="rerun",
            selection_mode="single-row",
            key="contacts_table",
            column_config={
                "contactable": st.column_config.CheckboxColumn("Contactable"),
                "last contacted": st.column_config.DatetimeColumn(format="YYYY-MM-DD"),
            },
        )
        if event.selection.rows:
            st.session_state["selected_contact_id"] = int(table.iloc[event.selection.rows[0]]["id"])
            st.success("Contact selected — open **Manage selected**.")

with tab_add:
    if not company_options:
        empty_state("Create a company first.")
    else:
        company_id = company_selector(company_options, key="contact_add_company")
        with db().session() as s:
            sources = [
                (src.id, src.title) for src in IntelligenceRepository(s).sources_for(company_id)
            ]
        with st.form("add_contact"):
            c1, c2 = st.columns(2)
            first = c1.text_input("First name *")
            last = c2.text_input("Last name *")
            c1, c2 = st.columns(2)
            title = c1.text_input("Job title")
            dept = c2.text_input("Department")
            c1, c2 = st.columns(2)
            email = c1.text_input("Professional e-mail")
            phone = c2.text_input("Business phone")
            profile = st.text_input("Public professional profile URL")
            source_id = st.selectbox(
                "Source of this contact data",
                [None] + [x[0] for x in sources],
                format_func=lambda i: "— none recorded —" if i is None else dict(sources)[i],
            )
            basis = st.text_area(
                "Lawful basis notes", "Legitimate interest: B2B prospecting of a professional role."
            )
            if st.form_submit_button("Add contact", type="primary"):
                run_action(
                    lambda s: ContactService(s, actor()).create(
                        ContactCreate(
                            company_id=company_id,
                            first_name=first,
                            last_name=last,
                            job_title=title or None,
                            department=dept or None,
                            professional_email=email or None,
                            business_phone=phone or None,
                            professional_profile_url=profile or None,
                            source_id=source_id,
                            lawful_basis_notes=basis or None,
                        )
                    ),
                    "Contact added.",
                    rerun=True,
                )

with tab_manage:
    contact_id = st.session_state.get("selected_contact_id")
    with db().session() as s:
        contact = ContactRepository(s).get(contact_id) if contact_id else None
        if contact:
            snapshot = {
                k: getattr(contact, k)
                for k in (
                    "id",
                    "company_id",
                    "first_name",
                    "last_name",
                    "job_title",
                    "department",
                    "professional_email",
                    "business_phone",
                    "professional_profile_url",
                    "lawful_basis_notes",
                    "contact_status",
                    "objection_status",
                    "source_id",
                    "created_at",
                    "last_contacted_at",
                    "anonymized_at",
                )
            }
            snapshot["company"] = contact.company.company_name
            reason = ComplianceService(s, actor()).suppression_reason(contact)
            history = [
                {"when": a.occurred_at, "type": a.activity_type, "subject": a.subject}
                for a in ActivityRepository(s).for_contact(contact.id)
            ]
    if not contact_id or not contact:
        empty_state("Select a contact in the Contacts tab.")
    else:
        st.subheader(f"{snapshot['first_name']} {snapshot['last_name']} — {snapshot['company']}")
        st.caption(
            f"Status: {snapshot['contact_status']} · objection: {snapshot['objection_status']} · "
            f"created {dt(snapshot['created_at'])} · "
            f"last contacted {dt(snapshot['last_contacted_at'])}"
        )
        if reason:
            st.warning(f"Outreach blocked — {reason}")
        if history:
            st.dataframe(pd.DataFrame(history), hide_index=True, width="stretch")

        if snapshot["contact_status"] != ContactStatus.ANONYMIZED.value:
            with st.form("edit_contact"):
                st.markdown("**Correct contact data** (right to rectification)")
                c1, c2 = st.columns(2)
                first = c1.text_input("First name", snapshot["first_name"])
                last = c2.text_input("Last name", snapshot["last_name"])
                c1, c2 = st.columns(2)
                title = c1.text_input("Job title", snapshot["job_title"] or "")
                dept = c2.text_input("Department", snapshot["department"] or "")
                c1, c2 = st.columns(2)
                email = c1.text_input("E-mail", snapshot["professional_email"] or "")
                phone = c2.text_input("Phone", snapshot["business_phone"] or "")
                profile = st.text_input("Profile URL", snapshot["professional_profile_url"] or "")
                basis = st.text_area("Lawful basis notes", snapshot["lawful_basis_notes"] or "")
                if st.form_submit_button("Save"):
                    run_action(
                        lambda s: ContactService(s, actor()).update(
                            contact_id,
                            ContactUpdate(
                                company_id=snapshot["company_id"],
                                first_name=first,
                                last_name=last,
                                job_title=title or None,
                                department=dept or None,
                                professional_email=email or None,
                                business_phone=phone or None,
                                professional_profile_url=profile or None,
                                source_id=snapshot["source_id"],
                                lawful_basis_notes=basis or None,
                            ),
                        ),
                        "Contact updated.",
                        rerun=True,
                    )

            c1, c2 = st.columns(2)
            with c1.container(border=True):
                st.markdown("**Status**")
                new_status = st.selectbox(
                    "Set status",
                    [c.value for c in ContactStatus if c != ContactStatus.ANONYMIZED],
                    index=0,
                    key="status_sel",
                )
                if st.button("Update status"):
                    run_action(
                        lambda s: ContactService(s, actor()).set_status(
                            contact_id, ContactStatus(new_status)
                        ),
                        "Status updated.",
                        rerun=True,
                    )
            with c2.container(border=True):
                st.markdown("**Objection** (right to object)")
                st.caption("Sets do-not-contact and adds the e-mail hash to the suppression list.")
                if st.button(
                    "Record objection", disabled=snapshot["objection_status"] == "objected"
                ):
                    run_action(
                        lambda s: ComplianceService(s, actor()).record_objection(contact_id),
                        "Objection recorded; contact suppressed.",
                        rerun=True,
                    )

            with st.expander("⚠️ Erasure: anonymize or delete"):
                st.markdown(
                    "- **Anonymize** removes personal data, keeps anonymous CRM history.\n"
                    "- **Delete** removes the contact row; activities stay without a contact.\n"
                    "In both cases the e-mail *hash* is kept on the suppression list to prevent "
                    "re-import (uncheck to remove completely)."
                )
                keep = st.checkbox("Keep e-mail hash on suppression list", value=True)
                confirm = st.text_input("Type ERASE to confirm")
                c1, c2 = st.columns(2)
                if c1.button("Anonymize", disabled=confirm != "ERASE"):
                    run_action(
                        lambda s: ComplianceService(s, actor()).anonymize_contact(contact_id, keep),
                        "Contact anonymized.",
                        rerun=True,
                    )
                if c2.button("Delete permanently", disabled=confirm != "ERASE"):

                    def _delete(s):  # type: ignore[no-untyped-def]
                        ComplianceService(s, actor()).delete_contact(contact_id, keep)
                        return True

                    if run_action(_delete):
                        st.session_state.pop("selected_contact_id", None)
                        st.session_state["_flash"] = "Contact deleted."
                        st.rerun()
        else:
            st.info(f"Anonymized on {dt(snapshot['anonymized_at'])}.")

        def _access(s):  # type: ignore[no-untyped-def]
            return ComplianceService(s, actor()).export_contact_data(contact_id)

        if st.button("Prepare data access export (JSON)"):
            data = run_action(_access)
            if data:
                st.download_button(
                    "Download contact data",
                    json.dumps(data, indent=2, ensure_ascii=False),
                    file_name=f"contact_{contact_id}_access_export.json",
                    mime="application/json",
                )

with tab_export:
    st.caption(
        "Exports exclude objected, anonymized and do-not-contact records by default. "
        "Every contact export is audited."
    )
    include = st.checkbox("Include restricted contacts (only for a documented purpose)")
    if st.button("Prepare contact export"):
        df = run_action(lambda s: ExportService(s, actor()).contacts(include_restricted=include))
        if df is not None:
            st.download_button(
                f"Download contacts.csv ({len(df)} rows)",
                to_safe_csv(df),
                file_name="cyberlead360_contacts.csv",
                mime="text/csv",
            )
