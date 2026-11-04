"""Shared fixtures: isolated in-memory databases, settings and fake providers."""

from __future__ import annotations

import os
from collections.abc import Iterator
from decimal import Decimal

import pytest
from pydantic import BaseModel
from sqlalchemy.orm import Session

# Tests must never touch the developer's real database or call real APIs.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["LLM_PROVIDER"] = "none"
os.environ["APP_ENV"] = "test"
os.environ["ENABLE_WEB_RETRIEVAL"] = "false"

from cyberlead360.config.settings import Settings
from cyberlead360.database import models  # noqa: F401
from cyberlead360.database.base import Base
from cyberlead360.database.session import create_db_engine, make_session_factory
from cyberlead360.domain.enums import (
    Confidence,
    FactType,
    Industry,
    ServiceLine,
    SourceType,
)
from cyberlead360.domain.schemas import (
    CompanyCreate,
    ContactCreate,
    FactCreate,
    OpportunityCreate,
    SourceCreate,
)
from cyberlead360.integrations.llm.base import LLMResult
from cyberlead360.services.company_service import CompanyService
from cyberlead360.services.contact_service import ContactService
from cyberlead360.services.enrichment_service import EnrichmentService
from cyberlead360.services.scoring_service import ScoringService

ACTOR = "test.user"


@pytest.fixture
def session() -> Iterator[Session]:
    """A fresh in-memory SQLite database (with FK enforcement) per test."""
    engine = create_db_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    s = factory()
    ScoringService(s, ACTOR).ensure_default_rules()
    s.flush()
    try:
        yield s
    finally:
        s.rollback()
        s.close()
        engine.dispose()


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, database_url="sqlite:///:memory:", llm_provider="none")


@pytest.fixture
def company_factory(session: Session):  # type: ignore[no-untyped-def]
    counter = {"n": 0}

    def make(**overrides):  # type: ignore[no-untyped-def]
        counter["n"] += 1
        n = counter["n"]
        data = {
            "company_name": f"Testco {chr(64 + n)}{n} Manufacturing",
            "website": f"https://www.testco-{n}.example",
            "industry": Industry.MANUFACTURING,
            "country": "FR",
            "employee_count": 400,
        }
        data.update(overrides)
        return CompanyService(session, ACTOR).create(
            CompanyCreate(**data), confirm_possible_duplicate=True
        )

    return make


@pytest.fixture
def contact_factory(session: Session):  # type: ignore[no-untyped-def]
    def make(company_id: int, email: str | None = None, **overrides):  # type: ignore[no-untyped-def]
        data = {
            "company_id": company_id,
            "first_name": "Camille",
            "last_name": "Test",
            "job_title": "CISO",
            "professional_email": email or f"camille.test{company_id}@testco.example",
        }
        data.update(overrides)
        return ContactService(session, ACTOR).create(ContactCreate(**data))

    return make


@pytest.fixture
def fact_factory(session: Session):  # type: ignore[no-untyped-def]
    def make(
        company_id: int,
        fact_type: FactType = FactType.SECURITY_SIGNAL,
        statement: str = "Announced a migration of its ERP to a public cloud provider.",
        approve: bool = True,
    ):  # type: ignore[no-untyped-def]
        svc = EnrichmentService(session, ACTOR)
        source = svc.add_source(
            SourceCreate(
                company_id=company_id,
                source_type=SourceType.PUBLIC_ANNOUNCEMENT,
                title="Test press release",
                url="https://www.testco.example/news/1",
            )
        )
        return svc.add_fact(
            FactCreate(
                company_id=company_id,
                source_id=source.id,
                fact_type=fact_type,
                statement=statement,
                confidence=Confidence.MEDIUM,
            ),
            approve=approve,
        )

    return make


@pytest.fixture
def opportunity_data():  # type: ignore[no-untyped-def]
    def make(company_id: int, value: str = "20000", probability: int = 30) -> OpportunityCreate:
        return OpportunityCreate(
            company_id=company_id,
            name="Pentest 2027",
            service_line=ServiceLine.PENETRATION_TESTING,
            estimated_value=Decimal(value),
            probability=probability,
        )

    return make


class FakeProvider:
    """Deterministic stand-in for an LLM provider (no network)."""

    name = "fake"
    model = "fake-model-1"

    def __init__(self, output: BaseModel | Exception) -> None:
        self.output = output
        self.calls: list[dict[str, object]] = []

    def generate_structured(self, *, system, user, schema, max_tokens):  # type: ignore[no-untyped-def]
        self.calls.append({"system": system, "user": user, "schema": schema})
        if isinstance(self.output, Exception):
            raise self.output
        return LLMResult(
            output=self.output,
            provider=self.name,
            model=self.model,
            input_tokens=1200,
            output_tokens=300,
            latency_ms=5,
        )
