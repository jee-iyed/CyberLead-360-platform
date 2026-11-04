"""Privacy controls: suppression, objections, anonymization, deletion, retention, access.

This module supports GDPR-style processes; it does not by itself make a
deployment compliant (see docs/GDPR.md).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from cyberlead360.database.models import (
    Activity,
    Contact,
    Meeting,
    OutreachDraft,
    SuppressionRecord,
)
from cyberlead360.database.repositories.activities import AuditRepository
from cyberlead360.database.repositories.contacts import ContactRepository, SuppressionRepository
from cyberlead360.domain.enums import ContactStatus, ObjectionStatus
from cyberlead360.domain.exceptions import NotFoundError, SuppressedContactError
from cyberlead360.utils.date_utils import utcnow
from cyberlead360.utils.normalization import email_hash, normalize_domain


def _serialize(value: object) -> object:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()  # type: ignore[no-any-return]
    return str(value)


class ComplianceService:
    def __init__(self, session: Session, actor: str) -> None:
        self.s = session
        self.actor = actor
        self.contacts = ContactRepository(session)
        self.suppressions = SuppressionRepository(session)
        self.audit = AuditRepository(session)

    def _contact(self, contact_id: int) -> Contact:
        contact = self.contacts.get(contact_id)
        if contact is None:
            raise NotFoundError("Contact", contact_id)
        return contact

    # ------------------------------------------------------------------ checks
    def is_email_suppressed(self, email: str | None) -> bool:
        if not email:
            return False
        if self.suppressions.by_email_hash(email_hash(email)):
            return True
        domain = email.rsplit("@", 1)[-1].lower()
        return self.suppressions.by_domain(domain) is not None

    def suppression_reason(self, contact: Contact) -> str | None:
        """Return why a contact must not be contacted, or ``None`` if allowed."""
        if contact.contact_status == ContactStatus.ANONYMIZED.value:
            return "Contact data has been anonymized."
        if contact.objection_status == ObjectionStatus.OBJECTED.value:
            return "The contact has objected to processing / prospecting."
        if contact.contact_status != ContactStatus.ACTIVE.value:
            return f"Contact status is '{contact.contact_status}'."
        if self.is_email_suppressed(contact.professional_email):
            return "The e-mail address or domain is on the suppression list."
        return None

    def assert_contactable(self, contact: Contact) -> None:
        reason = self.suppression_reason(contact)
        if reason:
            raise SuppressedContactError(f"Outreach blocked: {reason}")

    # ------------------------------------------------------------------ actions
    def record_objection(self, contact_id: int, reason: str = "Objection received") -> Contact:
        """Mark objection, set do-not-contact, and add the e-mail hash to suppression."""
        contact = self._contact(contact_id)
        contact.objection_status = ObjectionStatus.OBJECTED.value
        if contact.contact_status == ContactStatus.ACTIVE.value:
            contact.contact_status = ContactStatus.DO_NOT_CONTACT.value
        if contact.professional_email:
            self.suppress_email(contact.professional_email, reason)
        self.audit.record("contact", contact.id, "objection_recorded", self.actor)
        return contact

    def suppress_email(self, email: str, reason: str) -> SuppressionRecord:
        digest = email_hash(email)
        existing = self.suppressions.by_email_hash(digest)
        if existing:
            return existing
        record = self.suppressions.add(
            SuppressionRecord(email_sha256=digest, reason=reason[:200], created_by=self.actor)
        )
        self.audit.record("suppression", record.id, "email_suppressed", self.actor)
        return record

    def suppress_domain(self, domain_or_url: str, reason: str) -> SuppressionRecord:
        domain = normalize_domain(domain_or_url)
        if domain is None:
            raise ValueError("A domain is required")
        existing = self.suppressions.by_domain(domain)
        if existing:
            return existing
        record = self.suppressions.add(
            SuppressionRecord(domain=domain, reason=reason[:200], created_by=self.actor)
        )
        self.audit.record(
            "suppression", record.id, "domain_suppressed", self.actor, {"domain": domain}
        )
        return record

    def anonymize_contact(self, contact_id: int, keep_suppression: bool = True) -> Contact:
        """Irreversibly remove personal data while keeping aggregate CRM history.

        If ``keep_suppression`` the e-mail hash is retained on the suppression list
        so the person is not re-imported and contacted again.
        """
        contact = self._contact(contact_id)
        if keep_suppression and contact.professional_email:
            self.suppress_email(contact.professional_email, "Anonymized on request")
        contact.first_name = "Anonymized"
        contact.last_name = f"Contact {contact.id}"
        contact.professional_email = None
        contact.business_phone = None
        contact.professional_profile_url = None
        contact.lawful_basis_notes = None
        contact.department = None
        contact.contact_status = ContactStatus.ANONYMIZED.value
        contact.anonymized_at = utcnow()
        # Free-text notes may contain personal data: clear them on linked records.
        self.s.execute(
            update(Activity)
            .where(Activity.contact_id == contact.id)
            .values(notes="[removed: contact anonymized]")
        )
        self.s.execute(update(Meeting).where(Meeting.contact_id == contact.id).values(notes=None))
        self.s.execute(
            update(OutreachDraft)
            .where(OutreachDraft.contact_id == contact.id)
            .values(body="[removed: contact anonymized]", subject=None)
        )
        self.audit.record("contact", contact.id, "anonymized", self.actor)
        return contact

    def delete_contact(self, contact_id: int, keep_suppression: bool = True) -> None:
        """Hard-delete a contact (drafts cascade; activities keep a NULL contact)."""
        contact = self._contact(contact_id)
        if keep_suppression and contact.professional_email:
            self.suppress_email(contact.professional_email, "Deleted on request")
        self.s.execute(
            update(Activity)
            .where(Activity.contact_id == contact.id)
            .values(notes="[removed: contact deleted]")
        )
        self.s.delete(contact)
        self.audit.record("contact", contact_id, "deleted", self.actor)

    def retention_candidates(self, retention_days: int) -> list[Contact]:
        cutoff = utcnow() - timedelta(days=retention_days)
        return self.contacts.retention_candidates(cutoff)

    def apply_retention(self, retention_days: int) -> int:
        candidates = self.retention_candidates(retention_days)
        for contact in candidates:
            self.anonymize_contact(contact.id)
        self.audit.record(
            "contact",
            None,
            "retention_applied",
            self.actor,
            {"anonymized": len(candidates), "retention_days": retention_days},
        )
        return len(candidates)

    def export_contact_data(self, contact_id: int) -> dict[str, Any]:
        """Right-of-access export: everything stored about one contact."""
        contact = self._contact(contact_id)
        activities = self.s.scalars(select(Activity).where(Activity.contact_id == contact.id))
        meetings = self.s.scalars(select(Meeting).where(Meeting.contact_id == contact.id))
        drafts = self.s.scalars(select(OutreachDraft).where(OutreachDraft.contact_id == contact.id))
        self.audit.record("contact", contact.id, "access_export", self.actor)
        return {
            "contact": {
                col.name: _serialize(getattr(contact, col.name))
                for col in Contact.__table__.columns
            },
            "company": contact.company.company_name,
            "activities": [
                {
                    "type": a.activity_type,
                    "occurred_at": a.occurred_at.isoformat(),
                    "subject": a.subject,
                    "notes": a.notes,
                }
                for a in activities
            ],
            "meetings": [
                {"scheduled_at": m.scheduled_at.isoformat(), "status": m.status} for m in meetings
            ],
            "outreach_drafts": [
                {
                    "created_at": d.created_at.isoformat(),
                    "status": d.status,
                    "subject": d.subject,
                    "body": d.body,
                }
                for d in drafts
            ],
            "generated_at": utcnow().isoformat(),
        }
