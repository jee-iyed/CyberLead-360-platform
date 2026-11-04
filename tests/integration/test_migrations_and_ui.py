"""Alembic migrations match the ORM, the demo seed is coherent, and every page renders."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import func, inspect, select

from cyberlead360.database.base import Base
from cyberlead360.database.session import Database, create_db_engine, run_migrations

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]
PAGES = sorted((ROOT / "pages").glob("*.py"))


@pytest.fixture(scope="module")
def migrated_db_url(tmp_path_factory: pytest.TempPathFactory) -> str:
    path = tmp_path_factory.mktemp("db") / "migrated.db"
    url = f"sqlite:///{path.as_posix()}"
    run_migrations(url)
    return url


def test_migrations_create_all_tables_and_match_models(migrated_db_url: str) -> None:
    engine = create_db_engine(migrated_db_url)
    tables = set(inspect(engine).get_table_names())
    expected = {
        "companies",
        "contacts",
        "company_sources",
        "company_facts",
        "scoring_rules",
        "scoring_results",
        "outreach_drafts",
        "activities",
        "opportunities",
        "meetings",
        "suppression_records",
        "audit_events",
    }
    assert expected <= tables
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"Models and migrations diverge: {diff}"
    engine.dispose()


@pytest.fixture(scope="module")
def seeded_db(tmp_path_factory: pytest.TempPathFactory, migrated_db_url: str):  # type: ignore[no-untyped-def]
    from datetime import date

    from cyberlead360.config.settings import Settings
    from cyberlead360.demo_seed import seed

    settings = Settings(_env_file=None, database_url=migrated_db_url, auto_migrate=False)
    db = Database(settings)
    stats = seed(db, date(2026, 11, 4))
    return db, stats


def test_seed_is_deterministic_and_fictional(seeded_db) -> None:  # type: ignore[no-untyped-def]
    from cyberlead360.database.models import Company, CompanySource, Contact

    db, stats = seeded_db
    assert 50 <= stats["companies"] <= 100
    with db.session() as s:
        domains = list(
            s.scalars(
                select(Company.normalized_domain).where(Company.normalized_domain.is_not(None))
            )
        )
        emails = list(
            s.scalars(
                select(Contact.professional_email).where(Contact.professional_email.is_not(None))
            )
        )
        source_types = set(s.scalars(select(CompanySource.source_type)))
        names = list(s.scalars(select(Company.company_name).order_by(Company.id)))
    assert all(d.endswith(".example") for d in domains)
    assert all(e.endswith(".example") for e in emails)
    assert source_types <= {"demo_fictional", "manual_entry"}

    # Re-seeding a fresh database with the same anchor yields identical company names.
    from datetime import date

    from cyberlead360.config.settings import Settings
    from cyberlead360.demo_seed import seed

    other = Database(
        Settings(_env_file=None, database_url="sqlite:///:memory:", auto_migrate=False)
    )
    Base.metadata.create_all(other.engine)
    seed(other, date(2026, 11, 4))
    with other.session() as s:
        assert list(s.scalars(select(Company.company_name).order_by(Company.id))) == names
        assert s.scalar(select(func.count(Company.id))) == stats["companies"]


@pytest.mark.parametrize("page", ["app.py", *[p.name for p in PAGES]])
def test_every_page_renders_without_exception(page: str, seeded_db, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from streamlit.testing.v1 import AppTest

    from cyberlead360.config import settings as settings_module
    from cyberlead360.ui import bootstrap

    db, _ = seeded_db
    monkeypatch.setattr(bootstrap, "_database", lambda: db)
    monkeypatch.setattr(bootstrap, "_provider", lambda: None)
    monkeypatch.setattr(settings_module, "get_settings", lambda: db.settings)
    monkeypatch.setattr(bootstrap, "get_settings", lambda: db.settings)

    path = ROOT / ("app.py" if page == "app.py" else f"pages/{page}")
    at = AppTest.from_file(str(path), default_timeout=60)
    at.run()
    assert not at.exception, f"{page} raised: {[e.message for e in at.exception]}"
    assert len(at.title) >= 1
