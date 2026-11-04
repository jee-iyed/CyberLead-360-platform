"""Contact use cases. Contacts are personal data: every change is audited without values."""

from __future__ import annotations

from sqlalchemy.orm import Session

from cyberlead360.database.models import Contact
from cyberlead360.database.repositories.activities import AuditRepository
from cyberlead360.database.repositories.companies import CompanyRepository
from cyberlead360.database.repositories.contacts import ContactRepository
from cyberlead360.database.repositories.intelligence import IntelligenceRepository
from cyberlead360.domain.enums import ContactStatus
from cyberlead360.domain.exceptions import NotFoundError, ValidationFailedError
from cyberlead360.domain.schemas import ContactCreate, ContactUpdate
from cyberlead360.services.compliance_service import ComplianceService
from cyberlead360.utils.date_utils import utcnow


class ContactService:
    def __init__(self, session: Session, actor: str) -> None:
        self.s = session
        self.actor = actor
        self.repo = ContactRepository(session)
        self.companies = CompanyRepository(session)
        self.audit = AuditRepository(session)
        self.compliance = ComplianceService(session, actor)

    def get(self, contact_id: int) -> Contact:
        contact = self.repo.get(contact_id)
        if contact is None:
            raise NotFoundError("Contact", contact_id)
        return contact

    def _check_company_and_source(self, company_id: int, source_id: int | None) -> None:
        company = self.companies.get(company_id)
        if company is None:
            raise NotFoundError("Company", company_id)
        if company.is_archived:
            raise ValidationFailedError("Cannot add contacts to an archived company.")
        if source_id is not None:
            source = IntelligenceRepository(self.s).get_source(source_id)
            if source is None or source.company_id != company_id:
                raise ValidationFailedError("The source must belong to the same company.")

    def create(self, data: ContactCreate) -> Contact:
        self._check_company_and_source(data.company_id, data.source_id)
        email = str(data.professional_email) if data.professional_email else None
        if email and self.repo.by_email(data.company_id, email):
            raise ValidationFailedError(
                "A contact with this e-mail already exists for the company."
            )
        if email and self.compliance.is_email_suppressed(email):
            raise ValidationFailedError(
                "This e-mail is on the suppression list (objection or erasure). "
                "It cannot be re-added."
            )
        contact = Contact(
            company_id=data.company_id,
            first_name=data.first_name,
            last_name=data.last_name,
            job_title=data.job_title,
            department=data.department,
            professional_email=email,
            business_phone=data.business_phone,
            professional_profile_url=data.professional_profile_url,
            owner=data.owner or self.actor,
            source_id=data.source_id,
            source_collected_at=utcnow() if data.source_id else None,
            lawful_basis_notes=data.lawful_basis_notes,
        )
        self.repo.add(contact)
        self.audit.record(
            "contact", contact.id, "created", self.actor, {"company_id": data.company_id}
        )
        return contact

    def update(self, contact_id: int, data: ContactUpdate) -> Contact:
        contact = self.get(contact_id)
        if contact.contact_status == ContactStatus.ANONYMIZED.value:
            raise ValidationFailedError("Anonymized contacts cannot be edited.")
        if data.company_id != contact.company_id:
            raise ValidationFailedError("Moving a contact to another company is not supported.")
        self._check_company_and_source(data.company_id, data.source_id)
        values = data.model_dump()
        values["professional_email"] = (
            str(data.professional_email) if data.professional_email else None
        )
        if (
            values["professional_email"]
            and values["professional_email"] != contact.professional_email
        ) and self.repo.by_email(contact.company_id, values["professional_email"]):
            raise ValidationFailedError("Another contact of this company uses that e-mail.")
        changed = []
        for key, value in values.items():
            if getattr(contact, key) != value:
                setattr(contact, key, value)
                changed.append(key)
        if changed:
            self.audit.record("contact", contact.id, "updated", self.actor, {"fields": changed})
        return contact

    def set_status(self, contact_id: int, status: ContactStatus) -> Contact:
        contact = self.get(contact_id)
        if contact.contact_status == ContactStatus.ANONYMIZED.value:
            raise ValidationFailedError("Anonymized contacts cannot change status.")
        if status == ContactStatus.ANONYMIZED:
            raise ValidationFailedError("Use the anonymization workflow instead.")
        contact.contact_status = status.value
        self.audit.record(
            "contact", contact.id, "status_changed", self.actor, {"status": status.value}
        )
        return contact
