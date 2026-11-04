"""Domain enumerations.

``StrEnum`` values are stored as plain strings in the database, which keeps the
schema portable across SQLite and PostgreSQL and readable in exports.
"""

from __future__ import annotations

from enum import StrEnum


class Industry(StrEnum):
    MANUFACTURING = "manufacturing"
    HEALTHCARE = "healthcare"
    FINANCIAL_SERVICES = "financial_services"
    TECHNOLOGY = "technology"
    ENERGY_UTILITIES = "energy_utilities"
    TELECOM = "telecom"
    LOGISTICS = "logistics"
    RETAIL = "retail"
    PUBLIC_SECTOR = "public_sector"
    EDUCATION = "education"
    PROFESSIONAL_SERVICES = "professional_services"
    OTHER = "other"

    @property
    def label(self) -> str:
        return {
            "manufacturing": "Manufacturing / Industrial",
            "healthcare": "Healthcare",
            "financial_services": "Financial services",
            "technology": "Technology",
            "energy_utilities": "Energy & utilities",
            "telecom": "Telecommunications",
            "logistics": "Logistics & transport",
            "retail": "Retail & e-commerce",
            "public_sector": "Public sector",
            "education": "Education",
            "professional_services": "Professional services",
            "other": "Other",
        }[self.value]


class ProspectStage(StrEnum):
    """Lifecycle of a company as a prospect (the 12-stage CRM pipeline)."""

    NEW = "new"
    RESEARCHING = "researching"
    QUALIFIED = "qualified"
    READY_TO_CONTACT = "ready_to_contact"
    CONTACTED = "contacted"
    REPLIED = "replied"
    MEETING_SCHEDULED = "meeting_scheduled"
    OPPORTUNITY_OPEN = "opportunity_open"
    PROPOSAL_SENT = "proposal_sent"
    WON = "won"
    LOST = "lost"
    ARCHIVED = "archived"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()

    @property
    def order(self) -> int:
        """Funnel depth. LOST/ARCHIVED are terminal side states (not deeper)."""
        return _STAGE_ORDER[self]


_STAGE_ORDER: dict[ProspectStage, int] = {
    ProspectStage.NEW: 1,
    ProspectStage.RESEARCHING: 2,
    ProspectStage.QUALIFIED: 3,
    ProspectStage.READY_TO_CONTACT: 4,
    ProspectStage.CONTACTED: 5,
    ProspectStage.REPLIED: 6,
    ProspectStage.MEETING_SCHEDULED: 7,
    ProspectStage.OPPORTUNITY_OPEN: 8,
    ProspectStage.PROPOSAL_SENT: 9,
    ProspectStage.WON: 10,
    ProspectStage.LOST: 0,
    ProspectStage.ARCHIVED: 0,
}


class QualificationStatus(StrEnum):
    """Sales qualification decision — independent from the pipeline stage."""

    NOT_ASSESSED = "not_assessed"
    QUALIFIED = "qualified"
    NURTURE = "nurture"
    DISQUALIFIED = "disqualified"


class Priority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ContactStatus(StrEnum):
    ACTIVE = "active"
    DO_NOT_CONTACT = "do_not_contact"
    BOUNCED = "bounced"
    LEFT_COMPANY = "left_company"
    ANONYMIZED = "anonymized"


class ObjectionStatus(StrEnum):
    NONE = "none"
    OBJECTED = "objected"


class SourceType(StrEnum):
    MANUAL_ENTRY = "manual_entry"
    CSV_IMPORT = "csv_import"
    OFFICIAL_WEBSITE = "official_website"
    PUBLIC_ANNOUNCEMENT = "public_announcement"
    PUBLIC_REGISTRY = "public_registry"
    AUTHORIZED_API = "authorized_api"
    DEMO_FICTIONAL = "demo_fictional"


class VerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    REJECTED = "rejected"


class FactType(StrEnum):
    BUSINESS_CONTEXT = "business_context"
    TECHNOLOGY_CONTEXT = "technology_context"
    REGULATORY_CONTEXT = "regulatory_context"
    SECURITY_SIGNAL = "security_signal"
    SECURITY_NEED_EXPLICIT = "security_need_explicit"
    GROWTH_EVENT = "growth_event"
    OTHER = "other"

    @property
    def label(self) -> str:
        return {
            "business_context": "Business context",
            "technology_context": "Technology context",
            "regulatory_context": "Regulatory context",
            "security_signal": "Relevant public security signal",
            "security_need_explicit": "Explicit, sourced security need",
            "growth_event": "Growth event",
            "other": "Other",
        }[self.value]


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ActivityType(StrEnum):
    EMAIL_SENT = "email_sent"
    CALL = "call"
    LINKEDIN_MESSAGE = "linkedin_message"
    REPLY_RECEIVED = "reply_received"
    MEETING = "meeting"
    NOTE = "note"
    FOLLOW_UP = "follow_up"
    STAGE_CHANGE = "stage_change"

    @property
    def is_outbound_touch(self) -> bool:
        return self in {
            ActivityType.EMAIL_SENT,
            ActivityType.CALL,
            ActivityType.LINKEDIN_MESSAGE,
        }


class ActivityDirection(StrEnum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"
    INTERNAL = "internal"


class OpportunityStage(StrEnum):
    OPEN = "open"
    PROPOSAL_SENT = "proposal_sent"
    WON = "won"
    LOST = "lost"

    @property
    def is_closed(self) -> bool:
        return self in {OpportunityStage.WON, OpportunityStage.LOST}


class ServiceLine(StrEnum):
    PENETRATION_TESTING = "penetration_testing"
    WEB_SECURITY_AUDIT = "web_security_audit"
    NETWORK_ASSESSMENT = "network_assessment"
    CLOUD_SECURITY = "cloud_security"
    SECURITY_AWARENESS = "security_awareness"
    SOC_MDR = "soc_mdr"
    INCIDENT_RESPONSE_READINESS = "incident_response_readiness"
    COMPLIANCE_SUPPORT = "compliance_support"
    OT_SECURITY = "ot_security"

    @property
    def label(self) -> str:
        return {
            "penetration_testing": "Penetration testing",
            "web_security_audit": "Web security audit",
            "network_assessment": "Network security assessment",
            "cloud_security": "Cloud security",
            "security_awareness": "Security awareness",
            "soc_mdr": "SOC / MDR",
            "incident_response_readiness": "Incident response readiness",
            "compliance_support": "Compliance support",
            "ot_security": "Industrial / OT security",
        }[self.value]

    @property
    def label_fr(self) -> str:
        return {
            "penetration_testing": "Tests d'intrusion",
            "web_security_audit": "Audit de sécurité web",
            "network_assessment": "Évaluation de la sécurité réseau",
            "cloud_security": "Sécurité cloud",
            "security_awareness": "Sensibilisation à la sécurité",
            "soc_mdr": "SOC / MDR",
            "incident_response_readiness": "Préparation à la réponse aux incidents",
            "compliance_support": "Accompagnement à la conformité",
            "ot_security": "Sécurité industrielle / OT",
        }[self.value]


class MeetingStatus(StrEnum):
    SCHEDULED = "scheduled"
    HELD = "held"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class MessageType(StrEnum):
    COLD_EMAIL = "cold_email"
    LINKEDIN_CONNECTION = "linkedin_connection"
    FOLLOW_UP = "follow_up"
    MEETING_INVITATION = "meeting_invitation"
    POST_MEETING_FOLLOW_UP = "post_meeting_follow_up"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").capitalize()


class Tone(StrEnum):
    PROFESSIONAL = "professional"
    CONCISE = "concise"
    CONSULTATIVE = "consultative"
    TECHNICAL = "technical"
    EXECUTIVE = "executive"


class Language(StrEnum):
    EN = "en"
    FR = "fr"


class DraftStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    SENT_MANUALLY = "sent_manually"


class GenerationMode(StrEnum):
    TEMPLATE = "template"
    LLM = "llm"
