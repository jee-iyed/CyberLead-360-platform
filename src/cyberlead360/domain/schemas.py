"""Pydantic models validating data entering the application services.

These schemas are the single validation gate shared by forms, CSV import and
scripts, so a rule (e.g. domain normalization) is defined exactly once.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from cyberlead360.domain.enums import (
    ActivityDirection,
    ActivityType,
    Confidence,
    FactType,
    Industry,
    Language,
    MeetingStatus,
    MessageType,
    QualificationStatus,
    ServiceLine,
    SourceType,
    Tone,
)
from cyberlead360.utils.normalization import (
    collapse_whitespace,
    normalize_country,
    normalize_website,
)
from cyberlead360.utils.validators import clean_text, is_safe_http_url

ShortText = Annotated[str, Field(max_length=200)]


def _optional_clean(value: object, max_length: int) -> str | None:
    if value is None:
        return None
    return clean_text(str(value), max_length)


def parse_industry(value: object) -> Industry | None:
    """Accept enum values, labels or loose spellings ('Financial Services')."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, Industry):
        return value
    key = str(value).strip().casefold().replace("&", "and")
    for industry in Industry:
        candidates = {
            industry.value,
            industry.label.casefold().replace("&", "and"),
            industry.value.replace("_", " "),
        }
        if key in candidates:
            return industry
    aliases = {
        "industrial": Industry.MANUFACTURING,
        "industry": Industry.MANUFACTURING,
        "finance": Industry.FINANCIAL_SERVICES,
        "banking": Industry.FINANCIAL_SERVICES,
        "insurance": Industry.FINANCIAL_SERVICES,
        "health": Industry.HEALTHCARE,
        "tech": Industry.TECHNOLOGY,
        "software": Industry.TECHNOLOGY,
        "it": Industry.TECHNOLOGY,
        "energy": Industry.ENERGY_UTILITIES,
        "utilities": Industry.ENERGY_UTILITIES,
        "transport": Industry.LOGISTICS,
        "government": Industry.PUBLIC_SECTOR,
    }
    if key in aliases:
        return aliases[key]
    raise ValueError(f"Unknown industry {value!r}. Allowed: {', '.join(i.value for i in Industry)}")


class _Base(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


# --------------------------------------------------------------------------- companies
class CompanyCreate(_Base):
    company_name: str = Field(min_length=2, max_length=200)
    website: str | None = Field(default=None, max_length=300)
    industry: Industry | None = None
    subindustry: str | None = Field(default=None, max_length=120)
    country: str | None = None
    city: str | None = Field(default=None, max_length=120)
    employee_count: int | None = Field(default=None, ge=1, le=5_000_000)
    description: str | None = Field(default=None, max_length=4000)
    cybersecurity_interest: str | None = Field(default=None, max_length=2000)
    owner: str | None = Field(default=None, max_length=120)

    @field_validator("company_name", mode="before")
    @classmethod
    def _name(cls, v: object) -> object:
        return collapse_whitespace(str(v)) if v is not None else v

    @field_validator("website", mode="before")
    @classmethod
    def _website(cls, v: object) -> str | None:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return normalize_website(str(v))

    @field_validator("industry", mode="before")
    @classmethod
    def _industry(cls, v: object) -> Industry | None:
        return parse_industry(v)

    @field_validator("country", mode="before")
    @classmethod
    def _country(cls, v: object) -> str | None:
        return normalize_country(None if v is None else str(v))

    @field_validator(
        "subindustry", "city", "description", "cybersecurity_interest", "owner", mode="before"
    )
    @classmethod
    def _text(cls, v: object) -> str | None:
        return _optional_clean(v, 4000)

    @field_validator("employee_count", mode="before")
    @classmethod
    def _employees(cls, v: object) -> object:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        if isinstance(v, float):
            if v != v:  # NaN from pandas
                return None
            if not v.is_integer():
                raise ValueError("Employee count must be a whole number")
            return int(v)
        if isinstance(v, str):
            return v.replace(" ", "").replace(",", "")
        return v


class CompanyUpdate(CompanyCreate):
    """All fields re-validated on update; ``qualification_status`` editable here."""

    qualification_status: QualificationStatus = QualificationStatus.NOT_ASSESSED


# --------------------------------------------------------------------------- contacts
class ContactCreate(_Base):
    company_id: int
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    job_title: str | None = Field(default=None, max_length=150)
    department: str | None = Field(default=None, max_length=100)
    professional_email: EmailStr | None = None
    business_phone: str | None = Field(default=None, max_length=40)
    professional_profile_url: str | None = Field(default=None, max_length=300)
    owner: str | None = Field(default=None, max_length=120)
    source_id: int | None = None
    lawful_basis_notes: str | None = Field(default=None, max_length=1000)

    @field_validator("professional_email", mode="before")
    @classmethod
    def _email(cls, v: object) -> object:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return str(v).strip().lower()

    @field_validator("professional_profile_url", mode="before")
    @classmethod
    def _profile(cls, v: object) -> str | None:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        if not is_safe_http_url(str(v)):
            raise ValueError("Profile URL must be an http(s) URL")
        return str(v).strip()

    @field_validator("business_phone", mode="before")
    @classmethod
    def _phone(cls, v: object) -> str | None:
        text = _optional_clean(v, 40)
        if text and not all(c.isdigit() or c in "+-() ." for c in text):
            raise ValueError("Phone may only contain digits, spaces and + - ( ) .")
        return text

    @field_validator("job_title", "department", "owner", "lawful_basis_notes", mode="before")
    @classmethod
    def _text(cls, v: object) -> str | None:
        return _optional_clean(v, 1000)


class ContactUpdate(ContactCreate):
    pass


# --------------------------------------------------------------------------- intelligence
class SourceCreate(_Base):
    company_id: int
    source_type: SourceType
    title: str = Field(min_length=3, max_length=300)
    url: str | None = Field(default=None, max_length=1000)
    publisher: str | None = Field(default=None, max_length=200)
    published_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("url", mode="before")
    @classmethod
    def _url(cls, v: object) -> str | None:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        if not is_safe_http_url(str(v)):
            raise ValueError("Source URL must be an absolute http(s) URL")
        return str(v).strip()


class FactCreate(_Base):
    company_id: int
    source_id: int = Field(description="Every fact must reference a source.")
    fact_type: FactType
    statement: str = Field(min_length=5, max_length=1000)
    excerpt: str | None = Field(default=None, max_length=2000)
    confidence: Confidence = Confidence.MEDIUM
    observed_at: datetime | None = None

    @field_validator("statement", "excerpt", mode="before")
    @classmethod
    def _text(cls, v: object) -> str | None:
        return _optional_clean(v, 2000)


# --------------------------------------------------------------------------- CRM
class ActivityCreate(_Base):
    company_id: int
    activity_type: ActivityType
    direction: ActivityDirection = ActivityDirection.OUTBOUND
    contact_id: int | None = None
    opportunity_id: int | None = None
    subject: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=4000)
    occurred_at: datetime | None = None
    follow_up_at: datetime | None = None

    @field_validator("subject", "notes", mode="before")
    @classmethod
    def _text(cls, v: object) -> str | None:
        return _optional_clean(v, 4000)


class OpportunityCreate(_Base):
    company_id: int
    name: str = Field(min_length=3, max_length=200)
    service_line: ServiceLine
    estimated_value: Decimal = Field(ge=0, le=Decimal("100000000"), decimal_places=2)
    currency: str = Field(default="EUR", pattern=r"^[A-Z]{3}$")
    probability: int = Field(
        default=20,
        ge=0,
        le=100,
        description="Seller's forecast for weighted pipeline — NOT derived from the lead score.",
    )
    expected_close_date: date | None = None
    next_action: str | None = Field(default=None, max_length=300)
    next_action_date: date | None = None
    primary_contact_id: int | None = None


class MeetingCreate(_Base):
    company_id: int
    scheduled_at: datetime
    duration_minutes: int = Field(default=45, ge=5, le=480)
    contact_id: int | None = None
    opportunity_id: int | None = None
    meeting_type: str = Field(default="discovery", max_length=50)
    location: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=4000)
    status: MeetingStatus = MeetingStatus.SCHEDULED


class OutreachRequest(_Base):
    company_id: int
    contact_id: int | None = None
    message_type: MessageType = MessageType.COLD_EMAIL
    tone: Tone = Tone.PROFESSIONAL
    language: Language = Language.EN
    service_focus: ServiceLine | None = None
    sender_name: str = Field(default="Alex Martin", max_length=100)
    sender_company: str = Field(default="Your Security Firm", max_length=100)
    use_llm: bool = True


# --------------------------------------------------------------------------- AI outputs
class EvidenceRef(BaseModel):
    fact_id: int
    note: str = Field(max_length=300)


class CompanySummaryOutput(BaseModel):
    profile: str = Field(max_length=1500)
    business_context: list[str] = Field(default_factory=list, max_length=8)
    possible_service_alignment: list[str] = Field(default_factory=list, max_length=8)
    evidence: list[EvidenceRef] = Field(default_factory=list, max_length=20)
    unknowns: list[str] = Field(default_factory=list, max_length=10)


class ServiceSuggestion(BaseModel):
    service_line: ServiceLine
    rationale: str = Field(max_length=600)
    evidence_fact_ids: list[int] = Field(default_factory=list)
    strength: Confidence = Confidence.LOW


class OpportunityAnalysisOutput(BaseModel):
    suggestions: list[ServiceSuggestion] = Field(default_factory=list, max_length=9)
    caveats: list[str] = Field(default_factory=list, max_length=8)


class OutreachDraftOutput(BaseModel):
    subject: str | None = Field(default=None, max_length=200)
    body: str = Field(min_length=20, max_length=4000)
    evidence_fact_ids: list[int] = Field(default_factory=list)
    personalization_notes: list[str] = Field(default_factory=list, max_length=8)
