"""Companies: search, profile, edit, archive, create, CSV import, duplicates, export."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from cyberlead360.database.repositories.companies import CompanyFilters, CompanyRepository
from cyberlead360.domain.enums import Industry, ProspectStage, QualificationStatus
from cyberlead360.domain.schemas import CompanyCreate, CompanyUpdate
from cyberlead360.services.company_service import MERGEABLE_FIELDS, CompanyService
from cyberlead360.services.export_service import ExportService, to_safe_csv
from cyberlead360.services.import_service import ImportService
from cyberlead360.ui.bootstrap import actor, db, flash, page_setup, run_action, settings
from cyberlead360.ui.components import (
    country_label,
    dt,
    empty_state,
    industry_label,
    priority_pill,
    safe_link,
    stage_label,
)
from cyberlead360.utils.normalization import COUNTRIES

page_setup("Companies", "🏢")
flash()

INDUSTRIES = [i.value for i in Industry]
COUNTRY_CODES = sorted(COUNTRIES)
tab_browse, tab_profile, tab_add, tab_import, tab_dups, tab_export = st.tabs(
    [
        "🔎 Browse",
        "📄 Profile & edit",
        "➕ Add company",
        "📥 Import CSV",
        "🧬 Duplicates",
        "📤 Export",
    ]
)


def _company_form(prefix: str, defaults: dict | None = None) -> dict:
    d = defaults or {}
    c1, c2 = st.columns(2)
    values = {
        "company_name": c1.text_input(
            "Company name *", d.get("company_name", ""), key=f"{prefix}_n"
        ),
        "website": c2.text_input(
            "Website",
            d.get("website") or "",
            key=f"{prefix}_w",
            placeholder="https://www.company.example",
        ),
    }
    c1, c2, c3 = st.columns(3)
    ind = d.get("industry")
    values["industry"] = c1.selectbox(
        "Industry",
        [None, *INDUSTRIES],
        index=([None, *INDUSTRIES].index(ind) if ind in INDUSTRIES else 0),
        format_func=lambda v: "—" if v is None else Industry(v).label,
        key=f"{prefix}_i",
    )
    values["subindustry"] = c2.text_input(
        "Sub-industry", d.get("subindustry") or "", key=f"{prefix}_si"
    )
    cc = d.get("country")
    values["country"] = c3.selectbox(
        "Country",
        [None, *COUNTRY_CODES],
        index=([None, *COUNTRY_CODES].index(cc) if cc in COUNTRY_CODES else 0),
        format_func=lambda v: "—" if v is None else f"{COUNTRIES[v]} ({v})",
        key=f"{prefix}_c",
    )
    c1, c2, c3 = st.columns(3)
    values["city"] = c1.text_input("City", d.get("city") or "", key=f"{prefix}_ci")
    emp = c2.number_input(
        "Employees",
        min_value=0,
        value=int(d.get("employee_count") or 0),
        step=10,
        key=f"{prefix}_e",
        help="0 = unknown",
    )
    values["employee_count"] = int(emp) or None
    values["owner"] = c3.text_input("Owner", d.get("owner") or actor(), key=f"{prefix}_o")
    values["description"] = st.text_area(
        "Description (company information only)", d.get("description") or "", key=f"{prefix}_d"
    )
    values["cybersecurity_interest"] = st.text_area(
        "Documented cybersecurity interest (cite your source in Intelligence)",
        d.get("cybersecurity_interest") or "",
        key=f"{prefix}_ci2",
    )
    return values


# ----------------------------------------------------------------------------- browse
with tab_browse:
    with db().session() as s:
        repo = CompanyRepository(s)
        countries_present = repo.distinct_values("country")
    f1, f2, f3, f4 = st.columns([2, 2, 2, 2])
    search = f1.text_input("Search name, domain or city")
    industries = f2.multiselect("Industry", INDUSTRIES, format_func=lambda v: Industry(v).label)
    countries = f3.multiselect("Country", countries_present, format_func=country_label)
    stages = f4.multiselect("Stage", [s.value for s in ProspectStage], format_func=stage_label)
    f1, f2, f3 = st.columns([2, 2, 1])
    emp_range = f1.slider("Employees", 0, 20000, (0, 20000), step=50)
    score_range = f2.slider("Lead score", 0, 100, (0, 100))
    include_archived = f3.checkbox("Include archived")
    filters = CompanyFilters(
        search=search or None,
        industries=industries,
        countries=countries,
        stages=stages,
        min_employees=emp_range[0] or None,
        max_employees=None if emp_range[1] >= 20000 else emp_range[1],
        min_score=score_range[0] or None,
        max_score=None if score_range[1] >= 100 else score_range[1],
        include_archived=include_archived,
    )
    with db().session() as s:
        rows = CompanyService(s, actor()).search(filters)
        table = pd.DataFrame(
            [
                {
                    "id": c.id,
                    "company": c.company_name,
                    "score": score,
                    "priority": prio or "—",
                    "industry": industry_label(c.industry),
                    "country": c.country or "—",
                    "employees": c.employee_count,
                    "stage": stage_label(c.prospect_stage),
                    "domain": c.normalized_domain or "—",
                    "updated": c.updated_at,
                    "archived": c.archived_at is not None,
                }
                for c, score, prio in rows
            ]
        )
    st.caption(f"{len(table)} companies · sorted by priority (score) · select a row to open it")
    if table.empty:
        empty_state("No company matches these filters.")
    else:
        event = st.dataframe(
            table,
            hide_index=True,
            width="stretch",
            on_select="rerun",
            selection_mode="single-row",
            key="company_table",
            column_config={
                "score": st.column_config.ProgressColumn(
                    "Score", min_value=0, max_value=100, format="%d"
                ),
                "updated": st.column_config.DatetimeColumn("Updated", format="YYYY-MM-DD"),
            },
        )
        if event.selection.rows:
            st.session_state["selected_company_id"] = int(table.iloc[event.selection.rows[0]]["id"])
            st.success("Company selected — open the **Profile & edit** tab.")

# ----------------------------------------------------------------------------- profile
with tab_profile:
    with db().session() as s:
        options = CompanyRepository(s).options(include_archived=True)
    if not options:
        empty_state("No companies yet.")
    else:
        ids = [o[0] for o in options]
        names = dict(options)
        current = st.session_state.get("selected_company_id")
        cid = st.selectbox(
            "Company",
            ids,
            index=ids.index(current) if current in ids else 0,
            format_func=lambda i: f"{names[i]} (#{i})",
            key="profile_select",
        )
        st.session_state["selected_company_id"] = cid
        with db().session() as s:
            svc = CompanyService(s, actor())
            company = svc.get(cid)
            from cyberlead360.database.repositories.intelligence import IntelligenceRepository

            score = IntelligenceRepository(s).current_score(cid)
            data = {
                k: getattr(company, k)
                for k in (
                    "company_name",
                    "website",
                    "industry",
                    "subindustry",
                    "country",
                    "city",
                    "employee_count",
                    "description",
                    "cybersecurity_interest",
                    "owner",
                    "qualification_status",
                )
            }
            meta = {
                "stage": company.prospect_stage,
                "created": company.created_at,
                "updated": company.updated_at,
                "archived": company.archived_at,
                "merged_into": company.merged_into_id,
                "domain": company.normalized_domain,
                "contacts": len(company.contacts),
                "opps": len(company.opportunities),
                "range": company.employee_range,
                "last_activity": company.last_activity_at,
            }
            score_info = (score.total_score, score.priority, score.rules_version) if score else None

        h1, h2, h3, h4 = st.columns(4)
        h1.metric("Lead score", f"{score_info[0]}/100" if score_info else "—")
        h2.markdown(
            "**Priority**<br>" + priority_pill(score_info[1] if score_info else None),
            unsafe_allow_html=True,
        )
        h3.metric("Stage", stage_label(meta["stage"]))
        h4.metric("Contacts / deals", f"{meta['contacts']} / {meta['opps']}")
        st.caption(
            f"Domain: {meta['domain'] or '—'} · Size band: {meta['range'] or '—'} · "
            f"Created {dt(meta['created'])} · Updated {dt(meta['updated'], True)} · "
            f"Last activity {dt(meta['last_activity'])}"
        )
        safe_link("Open website", data["website"])
        if meta["merged_into"]:
            st.warning(f"This record was merged into company #{meta['merged_into']}.")

        if meta["archived"] is None:
            with st.form("edit_company"):
                st.subheader("Edit")
                values = _company_form("edit", data)
                values["qualification_status"] = st.selectbox(
                    "Qualification decision (separate from pipeline stage)",
                    [q.value for q in QualificationStatus],
                    index=[q.value for q in QualificationStatus].index(
                        data["qualification_status"]
                    ),
                )
                if st.form_submit_button("Save changes", type="primary"):
                    run_action(
                        lambda s: CompanyService(s, actor()).update(cid, CompanyUpdate(**values)),
                        "Company updated and re-scored.",
                        rerun=True,
                    )
            with st.expander("Archive company"):
                reason = st.text_input("Reason", key="arch_reason")
                confirm = st.checkbox("I confirm archiving this company (it can be restored).")
                if st.button("Archive", disabled=not (confirm and reason.strip())):
                    run_action(
                        lambda s: CompanyService(s, actor()).archive(cid, reason),
                        "Company archived.",
                        rerun=True,
                    )
        else:
            st.info(f"Archived on {dt(meta['archived'])}. Restore it to edit.")
            if not meta["merged_into"] and st.button("Restore company"):
                run_action(
                    lambda s: CompanyService(s, actor()).restore(cid),
                    "Company restored to stage New.",
                    rerun=True,
                )

# ----------------------------------------------------------------------------- add
with tab_add, st.form("add_company", clear_on_submit=False):
    values = _company_form("add")
    confirm_dup = st.checkbox(
        "Create even if a *possible* duplicate is detected "
        "(exact domain duplicates are always refused)"
    )
    if st.form_submit_button("Create company", type="primary"):

        def _create(s):  # type: ignore[no-untyped-def]
            return CompanyService(s, actor()).create(
                CompanyCreate(**{k: v for k, v in values.items() if v not in ("", None)}),
                confirm_possible_duplicate=confirm_dup,
            )

        created = run_action(_create)  # duplicates are reported as errors by run_action
        if created is not None:
            st.session_state["selected_company_id"] = created.id
            st.session_state["_flash"] = f"Company #{created.id} created and scored."
            st.rerun()

# ----------------------------------------------------------------------------- import
with tab_import:
    cfg = settings()
    st.markdown(
        f"Upload a UTF-8 CSV (max **{cfg.max_upload_mb:g} MB**, **{cfg.max_import_rows}** rows). "
        "Required column: `company_name`. Optional: `website, industry, subindustry, country, "
        "city, employee_count, description, cybersecurity_interest, owner`."
    )
    st.download_button(
        "Download CSV template",
        "company_name,website,industry,country,city,employee_count,description\n"
        "Example Manufacturing,https://www.example-manufacturing.example,manufacturing,FR,Lyon,450,"
        "Fictional example row\n",
        file_name="cyberlead360_import_template.csv",
        mime="text/csv",
    )
    upload = st.file_uploader("CSV file", type=["csv"], accept_multiple_files=False)
    if upload is not None:
        content = upload.getvalue()
        with db().session() as s:
            svc = ImportService(s, actor(), int(cfg.max_upload_mb * 1_048_576), cfg.max_import_rows)
            try:
                preview = svc.preview(content, upload.name)
            except Exception as exc:  # ImportValidationError and parse errors
                st.error(str(exc))
                preview = None
        if preview is not None:
            m = st.columns(5)
            m[0].metric("Rows", preview.total_rows)
            m[1].metric("New", preview.count("new"))
            m[2].metric("Possible duplicates", preview.count("possible_duplicate"))
            m[3].metric(
                "Duplicates (skipped)",
                preview.count("definite_duplicate") + preview.count("in_file_duplicate"),
            )
            m[4].metric("Invalid", len(preview.invalid))
            if preview.ignored_columns:
                st.warning(f"Ignored unknown columns: {', '.join(preview.ignored_columns)}")
            if preview.rows:
                st.dataframe(preview.preview_dataframe(), hide_index=True, width="stretch")
            if preview.invalid:
                st.error("Invalid rows are NOT imported. Fix them and re-upload:")
                invalid_df = preview.invalid_dataframe()
                st.dataframe(invalid_df, hide_index=True, width="stretch")
                st.download_button(
                    "Download invalid rows report",
                    to_safe_csv(invalid_df),
                    file_name="import_errors.csv",
                    mime="text/csv",
                )
            policy = st.radio(
                "Possible duplicates",
                ["skip", "create_flagged"],
                horizontal=True,
                format_func=lambda p: {
                    "skip": "Skip them (review later)",
                    "create_flagged": "Create them anyway",
                }[p],
            )
            importable = preview.count("new") + (
                preview.count("possible_duplicate") if policy == "create_flagged" else 0
            )
            if st.button(
                f"Import {importable} companies", type="primary", disabled=importable == 0
            ):

                def _commit(s):  # type: ignore[no-untyped-def]
                    svc2 = ImportService(
                        s, actor(), int(cfg.max_upload_mb * 1_048_576), cfg.max_import_rows
                    )
                    return svc2.commit(svc2.preview(content, upload.name), policy)

                result = run_action(_commit)
                if result:
                    st.success(
                        f"Created {result.created} · skipped duplicates "
                        f"{result.skipped_duplicates} · invalid {result.invalid}"
                    )

# ----------------------------------------------------------------------------- duplicates
with tab_dups:
    st.markdown(
        "Possible duplicates are detected by **normalized name** similarity "
        "(legal suffixes and accents ignored). Exact domain duplicates cannot exist "
        "(unique constraint). Merging is explicit and audited; the duplicate is archived."
    )
    with db().session() as s:
        pairs = CompanyService(s, actor()).duplicate_report()
    if not pairs:
        st.success("No possible duplicates found among active companies.")
    else:
        df = pd.DataFrame([p.__dict__ for p in pairs])
        st.dataframe(df, hide_index=True, width="stretch")
        labels = {
            i: f"#{p.first_id} {p.first_name} ⟷ #{p.second_id} {p.second_name} ({p.reason})"
            for i, p in enumerate(pairs)
        }
        idx = st.selectbox("Pair to resolve", list(labels), format_func=labels.get)
        pair = pairs[idx]
        keep = st.radio(
            "Keep as primary",
            [pair.first_id, pair.second_id],
            horizontal=True,
            format_func=lambda i: (
                f"#{i} {pair.first_name if i == pair.first_id else pair.second_name}"
            ),
        )
        other = pair.second_id if keep == pair.first_id else pair.first_id
        take = st.multiselect(
            "Overwrite these primary fields with the duplicate's values "
            "(empty primary fields are always filled)",
            list(MERGEABLE_FIELDS),
        )
        ok = st.checkbox(
            f"I confirm merging #{other} into #{keep}. Contacts, facts, activities "
            "and opportunities move to the primary record."
        )
        if st.button("Merge", type="primary", disabled=not ok):
            run_action(
                lambda s: CompanyService(s, actor()).merge(keep, other, take),
                f"Company #{other} merged into #{keep}.",
                rerun=True,
            )

# ----------------------------------------------------------------------------- export
with tab_export:
    include = st.checkbox("Include archived companies", key="exp_arch")
    with db().session() as s:
        export_df = ExportService(s, actor()).companies(include_archived=include)
    st.caption(
        f"{len(export_df)} rows · values are protected against spreadsheet formula injection."
    )
    st.download_button(
        "Download companies.csv",
        to_safe_csv(export_df),
        file_name="cyberlead360_companies.csv",
        mime="text/csv",
        type="primary",
    )
