"""SQLAlchemy 2.x ORM models (normalized relational schema).

Cascade policy
--------------
* Company → contacts / sources / facts / scores / drafts / activities /
  opportunities / meetings: ``ON DELETE CASCADE``. Companies are normally
  *archived*, not deleted; hard delete exists only for erasure requests.
* Contact → activities / meetings / opportunities: ``SET NULL`` so commercial
  history survives contact deletion (anonymization keeps the row).
* Source → facts: ``RESTRICT`` — a source with facts cannot disappear silently.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cyberlead360.database.base import Base, TimestampMixin, UTCDateTime
from cyberlead360.domain.enums import (
    ActivityDirection,
    ActivityType,
    Confidence,
    ContactStatus,
    DraftStatus,
    FactType,
    GenerationMode,
    MeetingStatus,
    ObjectionStatus,
    OpportunityStage,
    Priority,
    ProspectStage,
    QualificationStatus,
    ReviewStatus,
    SourceType,
    VerificationStatus,
)
from cyberlead360.utils.date_utils import utcnow


def _enum_check(column: str, enum: type) -> CheckConstraint:
    values = ", ".join(f"'{e.value}'" for e in enum)
    return CheckConstraint(f"{column} IN ({values})", name=f"{column}_valid")


class Company(TimestampMixin, Base):
    __tablename__ = "companies"
    __table_args__ = (
        _enum_check("prospect_stage", ProspectStage),
        _enum_check("qualification_status", QualificationStatus),
        CheckConstraint("employee_count IS NULL OR employee_count > 0", name="employees_positive"),
        Index("ix_companies_stage_archived", "prospect_stage", "archived_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    website: Mapped[str | None] = mapped_column(String(300))
    # Unique when present: the primary deduplication key. NULLs are allowed many times.
    normalized_domain: Mapped[str | None] = mapped_column(String(255), unique=True)
    industry: Mapped[str | None] = mapped_column(String(40), index=True)
    subindustry: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str | None] = mapped_column(String(2), index=True)
    city: Mapped[str | None] = mapped_column(String(120))
    employee_count: Mapped[int | None] = mapped_column(Integer)
    employee_range: Mapped[str | None] = mapped_column(String(20))
    description: Mapped[str | None] = mapped_column(Text)
    cybersecurity_interest: Mapped[str | None] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(String(120))

    qualification_status: Mapped[str] = mapped_column(
        String(20), default=QualificationStatus.NOT_ASSESSED.value, nullable=False
    )
    prospect_stage: Mapped[str] = mapped_column(
        String(30), default=ProspectStage.NEW.value, nullable=False
    )
    highest_stage_order: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    stage_changed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_activity_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    merged_into_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL")
    )

    contacts: Mapped[list[Contact]] = relationship(
        back_populates="company", cascade="all, delete-orphan", passive_deletes=True
    )
    sources: Mapped[list[CompanySource]] = relationship(
        back_populates="company", cascade="all, delete-orphan", passive_deletes=True
    )
    facts: Mapped[list[CompanyFact]] = relationship(
        back_populates="company", cascade="all, delete-orphan", passive_deletes=True
    )
    opportunities: Mapped[list[Opportunity]] = relationship(
        back_populates="company", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def stage(self) -> ProspectStage:
        return ProspectStage(self.prospect_stage)

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None


class CompanySource(Base):
    __tablename__ = "company_sources"
    __table_args__ = (
        _enum_check("source_type", SourceType),
        _enum_check("verification_status", VerificationStatus),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    url: Mapped[str | None] = mapped_column(String(1000))
    publisher: Mapped[str | None] = mapped_column(String(200))
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    collected_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    collected_by: Mapped[str | None] = mapped_column(String(120))
    verification_status: Mapped[str] = mapped_column(
        String(20), default=VerificationStatus.UNVERIFIED.value, nullable=False
    )
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)

    company: Mapped[Company] = relationship(back_populates="sources")
    facts: Mapped[list[CompanyFact]] = relationship(back_populates="source")


class CompanyFact(Base):
    __tablename__ = "company_facts"
    __table_args__ = (
        _enum_check("fact_type", FactType),
        _enum_check("confidence", Confidence),
        _enum_check("review_status", ReviewStatus),
        Index("ix_company_facts_company_review", "company_id", "review_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    # NOT NULL: a fact without a traceable source cannot exist.
    source_id: Mapped[int] = mapped_column(
        ForeignKey("company_sources.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    fact_type: Mapped[str] = mapped_column(String(40), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    excerpt: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(10), default=Confidence.MEDIUM.value)
    observed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    review_status: Mapped[str] = mapped_column(
        String(20), default=ReviewStatus.PENDING.value, nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    reviewed_by: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)

    company: Mapped[Company] = relationship(back_populates="facts")
    source: Mapped[CompanySource] = relationship(back_populates="facts")


class Contact(TimestampMixin, Base):
    __tablename__ = "contacts"
    __table_args__ = (
        _enum_check("contact_status", ContactStatus),
        _enum_check("objection_status", ObjectionStatus),
        UniqueConstraint("company_id", "professional_email", name="uq_contacts_company_email"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    job_title: Mapped[str | None] = mapped_column(String(150))
    department: Mapped[str | None] = mapped_column(String(100))
    professional_email: Mapped[str | None] = mapped_column(String(254), index=True)
    business_phone: Mapped[str | None] = mapped_column(String(40))
    professional_profile_url: Mapped[str | None] = mapped_column(String(300))
    owner: Mapped[str | None] = mapped_column(String(120))
    contact_status: Mapped[str] = mapped_column(
        String(20), default=ContactStatus.ACTIVE.value, nullable=False
    )
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("company_sources.id", ondelete="SET NULL")
    )
    source_collected_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    lawful_basis_notes: Mapped[str | None] = mapped_column(Text)
    objection_status: Mapped[str] = mapped_column(
        String(20), default=ObjectionStatus.NONE.value, nullable=False
    )
    last_contacted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    anonymized_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    company: Mapped[Company] = relationship(back_populates="contacts")

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def can_be_contacted(self) -> bool:
        return (
            self.contact_status == ContactStatus.ACTIVE.value
            and self.objection_status == ObjectionStatus.NONE.value
        )


class ScoringRule(Base):
    """A versioned scoring configuration (JSON). Exactly one row is active."""

    __tablename__ = "scoring_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class ScoringResult(Base):
    __tablename__ = "scoring_results"
    __table_args__ = (
        _enum_check("priority", Priority),
        CheckConstraint("total_score BETWEEN 0 AND 100", name="score_range"),
        Index("ix_scoring_results_company_current", "company_id", "is_current"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    scoring_rule_id: Mapped[int] = mapped_column(
        ForeignKey("scoring_rules.id", ondelete="RESTRICT"), nullable=False
    )
    rules_version: Mapped[int] = mapped_column(Integer, nullable=False)
    total_score: Mapped[int] = mapped_column(Integer, nullable=False)
    priority: Mapped[str] = mapped_column(String(10), nullable=False)
    breakdown: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    missing_information: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    data_completeness: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_confidence: Mapped[str] = mapped_column(String(10), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class OutreachDraft(TimestampMixin, Base):
    __tablename__ = "outreach_drafts"
    __table_args__ = (
        _enum_check("status", DraftStatus),
        _enum_check("generation_mode", GenerationMode),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"))
    message_type: Mapped[str] = mapped_column(String(40), nullable=False)
    language: Mapped[str] = mapped_column(String(2), nullable=False)
    tone: Mapped[str] = mapped_column(String(20), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    generation_mode: Mapped[str] = mapped_column(String(10), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(80))
    evidence_fact_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default=DraftStatus.DRAFT.value, nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    approved_by: Mapped[str | None] = mapped_column(String(120))


class Opportunity(TimestampMixin, Base):
    __tablename__ = "opportunities"
    __table_args__ = (
        _enum_check("stage", OpportunityStage),
        CheckConstraint("estimated_value >= 0", name="value_non_negative"),
        CheckConstraint("probability BETWEEN 0 AND 100", name="probability_range"),
        Index("ix_opportunities_stage", "stage"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    primary_contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    service_line: Mapped[str] = mapped_column(String(40), nullable=False)
    stage: Mapped[str] = mapped_column(
        String(20), default=OpportunityStage.OPEN.value, nullable=False
    )
    estimated_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    probability: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    expected_close_date: Mapped[date | None] = mapped_column(Date)
    next_action: Mapped[str | None] = mapped_column(String(300))
    next_action_date: Mapped[date | None] = mapped_column(Date)
    won_lost_reason: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    company: Mapped[Company] = relationship(back_populates="opportunities")


class Activity(Base):
    __tablename__ = "activities"
    __table_args__ = (
        _enum_check("activity_type", ActivityType),
        _enum_check("direction", ActivityDirection),
        Index("ix_activities_company_occurred", "company_id", "occurred_at"),
        Index("ix_activities_follow_up", "follow_up_at", "follow_up_done"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), index=True
    )
    opportunity_id: Mapped[int | None] = mapped_column(
        ForeignKey("opportunities.id", ondelete="SET NULL")
    )
    activity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    follow_up_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    follow_up_done: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class Meeting(TimestampMixin, Base):
    __tablename__ = "meetings"
    __table_args__ = (
        _enum_check("status", MeetingStatus),
        CheckConstraint("duration_minutes > 0", name="duration_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    opportunity_id: Mapped[int | None] = mapped_column(
        ForeignKey("opportunities.id", ondelete="SET NULL")
    )
    scheduled_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=45, nullable=False)
    meeting_type: Mapped[str] = mapped_column(String(50), default="discovery", nullable=False)
    location: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(20), default=MeetingStatus.SCHEDULED.value, nullable=False
    )


class SuppressionRecord(Base):
    """Do-not-contact list. Stores a SHA-256 hash of the e-mail, not the e-mail itself."""

    __tablename__ = "suppression_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    email_sha256: Mapped[str | None] = mapped_column(String(64), unique=True)
    domain: Mapped[str | None] = mapped_column(String(255), unique=True)
    reason: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("email_sha256 IS NOT NULL OR domain IS NOT NULL", name="has_target"),
    )


class AuditEvent(Base):
    """Append-only accountability log. ``details`` must never contain personal data."""

    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_entity", "entity_type", "entity_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, nullable=False, index=True
    )
