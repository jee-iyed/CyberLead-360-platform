"""Company service, deduplication, merge, CSV import, export and DB constraints."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from cyberlead360.database.models import AuditEvent, Company, CompanyFact, Contact
from cyberlead360.domain.enums import FactType, ProspectStage
from cyberlead360.domain.exceptions import DuplicateCompanyError, ValidationFailedError
from cyberlead360.domain.schemas import CompanyCreate, CompanyUpdate
from cyberlead360.services.company_service import CompanyService
from cyberlead360.services.export_service import ExportService, safe_export_path, to_safe_csv
from cyberlead360.services.import_service import ImportService
from cyberlead360.services.pipeline_service import PipelineService
from tests.conftest import ACTOR

pytestmark = pytest.mark.integration


def test_create_company_normalizes_scores_and_audits(session, company_factory) -> None:  # type: ignore[no-untyped-def]
    company = company_factory(company_name="Nordel Industries SAS", website="WWW.NORDEL.example")
    assert company.normalized_name == "nordel industries"
    assert company.normalized_domain == "nordel.example"
    assert company.employee_range == "201-500"
    assert company.prospect_stage == ProspectStage.NEW.value
    assert company.created_at.tzinfo is not None
    from cyberlead360.database.repositories.intelligence import IntelligenceRepository

    score = IntelligenceRepository(session).current_score(company.id)
    assert score is not None and score.total_score == 65 and score.rules_version == 1
    audit = session.scalars(select(AuditEvent).where(AuditEvent.entity_id == company.id)).all()
    assert any(e.action == "created" for e in audit)


def test_definite_and_possible_duplicates(session, company_factory) -> None:  # type: ignore[no-untyped-def]
    company_factory(company_name="Helion Santé", website="https://helion.example")
    svc = CompanyService(session, ACTOR)
    with pytest.raises(DuplicateCompanyError, match="already uses this domain"):
        svc.create(CompanyCreate(company_name="Other name", website="http://www.helion.example/x"))
    with pytest.raises(DuplicateCompanyError, match="Possible duplicate"):
        svc.create(CompanyCreate(company_name="HELION SANTE SA", country="FR"))
    created = svc.create(
        CompanyCreate(company_name="Helion Sante SA", country="FR"), confirm_possible_duplicate=True
    )
    assert created.id
    pairs = svc.duplicate_report()
    assert pairs and pairs[0].reason == "Same normalized name"


def test_update_detects_domain_conflict_and_records_fields(session, company_factory) -> None:  # type: ignore[no-untyped-def]
    a = company_factory(website="https://alpha.example")
    b = company_factory(website="https://beta.example")
    svc = CompanyService(session, ACTOR)
    with pytest.raises(DuplicateCompanyError):
        svc.update(b.id, CompanyUpdate(company_name=b.company_name, website="alpha.example"))
    svc.update(
        a.id, CompanyUpdate(company_name=a.company_name, website=a.website, employee_count=20)
    )
    assert a.employee_range == "11-50"


def test_merge_moves_children_and_archives_duplicate(  # type: ignore[no-untyped-def]
    session, company_factory, contact_factory, fact_factory
) -> None:
    primary = company_factory(company_name="Vectra Systems", website=None, city=None)
    dup = company_factory(
        company_name="Vectra Systemes", website="https://vectra.example", city="Lyon"
    )
    contact_factory(primary.id, email="same@vectra.example")
    contact_factory(dup.id, email="same@vectra.example")  # same person on both records
    contact_factory(dup.id, email="other@vectra.example")
    fact_factory(dup.id, FactType.SECURITY_NEED_EXPLICIT)

    merged = CompanyService(session, ACTOR).merge(primary.id, dup.id)
    assert merged.normalized_domain == "vectra.example"
    assert merged.city == "Lyon"
    emails = sorted(
        c.professional_email
        for c in session.scalars(select(Contact).where(Contact.company_id == primary.id))
    )
    assert emails == ["other@vectra.example", "same@vectra.example"]
    assert session.scalars(select(CompanyFact).where(CompanyFact.company_id == primary.id)).all()
    session.refresh(dup)
    assert dup.merged_into_id == primary.id and dup.archived_at is not None
    assert dup.normalized_domain is None
    from cyberlead360.database.repositories.intelligence import IntelligenceRepository

    assert IntelligenceRepository(session).current_score(primary.id).total_score == 100
    with pytest.raises(ValidationFailedError):
        CompanyService(session, ACTOR).merge(primary.id, primary.id)


def test_archive_requires_closed_opportunities(session, company_factory, opportunity_data) -> None:  # type: ignore[no-untyped-def]
    company = company_factory()
    opp = PipelineService(session, ACTOR).create_opportunity(opportunity_data(company.id))
    svc = CompanyService(session, ACTOR)
    with pytest.raises(ValidationFailedError):
        svc.archive(company.id, "test")
    from cyberlead360.domain.enums import OpportunityStage

    PipelineService(session, ACTOR).move_opportunity(opp.id, OpportunityStage.LOST, "Budget")
    svc.archive(company.id, "no budget")
    assert company.is_archived and company.prospect_stage == "archived"
    svc.restore(company.id)
    assert not company.is_archived and company.prospect_stage == "new"


def test_database_enforces_constraints(session, company_factory) -> None:  # type: ignore[no-untyped-def]
    company = company_factory(website="https://unique.example")
    session.add(Company(company_name="X", normalized_name="x", normalized_domain="unique.example"))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()
    session.add(Company(company_name="Y", normalized_name="y", prospect_stage="not_a_stage"))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()
    # Facts cannot exist without a source (NOT NULL + FK)
    session.add(
        CompanyFact(company_id=company.id, source_id=999_999, fact_type="other", statement="x")
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


CSV = (
    b"Company,Website,Sector,Country,Employees,Unknown\n"
    b"Acme Industries,acme.example,manufacturing,France,450,x\n"
    b"Acme Industries SA,,manufacturing,FR,,x\n"  # in-file duplicate (same normalized name)
    b"Beta Health,beta.example,health,BE,120,x\n"
    b"B,bad domain,healthcare,Narnia,-5,x\n"  # invalid row
    b"Existing Co,existing.example,technology,DE,30,x\n"  # duplicate of DB record
)


def test_csv_import_reports_every_row(session, company_factory) -> None:  # type: ignore[no-untyped-def]
    company_factory(company_name="Existing Co", website="https://existing.example")
    svc = ImportService(session, ACTOR, max_bytes=1_000_000, max_rows=100)
    preview = svc.preview(CSV, "prospects.csv")
    statuses = {r.row_number: r.duplicate_status for r in preview.rows}
    assert statuses == {2: "new", 3: "in_file_duplicate", 4: "new", 6: "definite_duplicate"}
    assert [i.row_number for i in preview.invalid] == [5]
    assert len(preview.invalid[0].errors) >= 3  # name, domain, country, employees...
    assert preview.ignored_columns == ["unknown"]
    assert preview.total_rows == len(preview.rows) + len(preview.invalid)  # nothing dropped

    result = svc.commit(preview)
    assert (result.created, result.skipped_duplicates, result.invalid) == (2, 2, 1)
    assert not preview.invalid_dataframe().empty


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"", "empty"),
        (b"website\nx.example\n", "Missing required column"),
        (b"company_name\n" + b"A Company\n" * 11, "Too many rows"),
        (b"company_name\n" + b"x" * 2000, "too large"),
    ],
)
def test_csv_import_rejects_unusable_files(session, content: bytes, message: str) -> None:  # type: ignore[no-untyped-def]
    from cyberlead360.domain.exceptions import ImportValidationError

    svc = ImportService(session, ACTOR, max_bytes=1000, max_rows=10)
    with pytest.raises(ImportValidationError, match=message):
        svc.preview(content, "f.csv")


def test_exports_are_safe(session, company_factory, contact_factory, tmp_path) -> None:  # type: ignore[no-untyped-def]
    company = company_factory(company_name="=cmd|' /C calc'!A0 Corp")
    contact_factory(company.id)
    exp = ExportService(session, ACTOR)
    csv_text = to_safe_csv(exp.companies()).decode("utf-8-sig")
    assert "'=cmd" in csv_text
    assert len(exp.contacts()) == 1
    path = exp.write_to_disk(exp.companies(), tmp_path, "companies")
    assert path.parent == tmp_path.resolve() and path.exists()
    with pytest.raises(ValidationFailedError):
        safe_export_path(tmp_path, "../../etc/passwd")
