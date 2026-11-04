"""Normalization utilities and input schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cyberlead360.domain.enums import Industry
from cyberlead360.domain.schemas import CompanyCreate, ContactCreate, SourceCreate
from cyberlead360.utils.normalization import (
    email_hash,
    employee_range,
    name_similarity,
    normalize_company_name,
    normalize_country,
    normalize_domain,
)
from cyberlead360.utils.validators import escape_markdown, neutralize_csv_formula


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Acme SAS", "acme"),
        ("ACME s.a.", "acme"),
        ("Société Générale d'Équipement", "societe generale d equipement"),
        ("Smith & Sons Ltd", "smith and sons"),
        ("Group", "group"),  # a lone suffix-like token is kept
    ],
)
def test_normalize_company_name(raw: str, expected: str) -> None:
    assert normalize_company_name(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://www.Example.com/path?q=1", "example.com"),
        ("example.com", "example.com"),
        ("http://sub.example.co.uk:8080/", "sub.example.co.uk"),
        ("  ", None),
        (None, None),
    ],
)
def test_normalize_domain(raw: str | None, expected: str | None) -> None:
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize(
    "bad",
    [
        "ftp://example.com",
        "https://user:pw@example.com",
        "localhost",
        "https://10.0.0.1",
        "exa mple",
    ],
)
def test_normalize_domain_rejects_invalid(bad: str) -> None:
    with pytest.raises(ValueError):
        normalize_domain(bad)


def test_country_and_employee_range() -> None:
    assert normalize_country("France") == "FR"
    assert normalize_country("allemagne") == "DE"
    assert normalize_country("uk") == "GB"
    with pytest.raises(ValueError):
        normalize_country("Atlantis")
    assert employee_range(10) == "1-10"
    assert employee_range(5001) == "5001+"
    assert employee_range(None) is None


def test_similarity_and_hash() -> None:
    assert name_similarity("nordel industries", "nordel industrie") > 0.9
    assert name_similarity("alpha", "omega") < 0.5
    assert email_hash(" Jane@Example.COM ") == email_hash("jane@example.com")
    assert len(email_hash("a@b.example")) == 64


def test_company_create_normalizes_inputs() -> None:
    data = CompanyCreate(
        company_name="  Acme   Industries  ",
        website="WWW.ACME.example/about",
        industry="Financial Services",
        country="belgique",
        employee_count="1 200",
    )
    assert data.company_name == "Acme Industries"
    assert data.website == "https://acme.example"
    assert data.industry == Industry.FINANCIAL_SERVICES
    assert data.country == "BE"
    assert data.employee_count == 1200


@pytest.mark.parametrize(
    "overrides",
    [
        {"company_name": "A"},
        {"employee_count": 0},
        {"employee_count": 12.5},
        {"industry": "astrology"},
        {"website": "javascript:alert(1)"},
        {"unexpected": "field"},
    ],
)
def test_company_create_rejects_invalid(overrides: dict) -> None:
    data = {"company_name": "Valid Name"} | overrides
    with pytest.raises(ValidationError):
        CompanyCreate(**data)


def test_contact_and_source_validation() -> None:
    with pytest.raises(ValidationError):
        ContactCreate(
            company_id=1, first_name="A", last_name="B", professional_email="not-an-email"
        )
    with pytest.raises(ValidationError):
        ContactCreate(
            company_id=1, first_name="A", last_name="B", professional_profile_url="javascript:x"
        )
    with pytest.raises(ValidationError):
        SourceCreate(company_id=1, source_type="official_website", title="Home", url="file:///etc")


def test_csv_formula_and_markdown_escaping() -> None:
    assert neutralize_csv_formula("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert neutralize_csv_formula("@SUM") == "'@SUM"
    assert neutralize_csv_formula("normal") == "normal"
    assert neutralize_csv_formula(5) == 5
    assert escape_markdown("[click](http://x)") == r"\[click\]\(http://x\)"
