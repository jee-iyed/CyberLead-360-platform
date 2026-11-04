"""Contact and suppression data access."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from cyberlead360.database.models import Company, Contact, SuppressionRecord


class ContactRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def get(self, contact_id: int) -> Contact | None:
        return self.s.get(Contact, contact_id)

    def add(self, contact: Contact) -> Contact:
        self.s.add(contact)
        self.s.flush()
        return contact

    def for_company(self, company_id: int) -> list[Contact]:
        return list(
            self.s.scalars(
                select(Contact)
                .where(Contact.company_id == company_id)
                .order_by(Contact.last_name, Contact.first_name)
            )
        )

    def by_email(self, company_id: int, email: str) -> Contact | None:
        return self.s.scalar(
            select(Contact).where(
                Contact.company_id == company_id, Contact.professional_email == email
            )
        )

    def search(
        self,
        text: str | None = None,
        company_id: int | None = None,
        statuses: list[str] | None = None,
    ) -> list[tuple[Contact, str]]:
        stmt = select(Contact, Company.company_name).join(Company)
        if company_id:
            stmt = stmt.where(Contact.company_id == company_id)
        if statuses:
            stmt = stmt.where(Contact.contact_status.in_(statuses))
        if text:
            term = text.strip().lower().replace("%", "\\%").replace("_", "\\_")
            like = f"%{term}%"
            stmt = stmt.where(
                or_(
                    func.lower(Contact.first_name).like(like, escape="\\"),
                    func.lower(Contact.last_name).like(like, escape="\\"),
                    func.lower(Contact.job_title).like(like, escape="\\"),
                    func.lower(Company.company_name).like(like, escape="\\"),
                )
            )
        stmt = stmt.order_by(Company.company_name, Contact.last_name)
        return [(r[0], r[1]) for r in self.s.execute(stmt)]

    def retention_candidates(self, cutoff: datetime) -> list[Contact]:
        """Non-anonymized contacts not contacted (or created) since ``cutoff``."""
        last_touch = func.coalesce(Contact.last_contacted_at, Contact.created_at)
        return list(
            self.s.scalars(
                select(Contact).where(Contact.anonymized_at.is_(None), last_touch < cutoff)
            )
        )


class SuppressionRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def by_email_hash(self, digest: str) -> SuppressionRecord | None:
        return self.s.scalar(
            select(SuppressionRecord).where(SuppressionRecord.email_sha256 == digest)
        )

    def by_domain(self, domain: str) -> SuppressionRecord | None:
        return self.s.scalar(select(SuppressionRecord).where(SuppressionRecord.domain == domain))

    def add(self, record: SuppressionRecord) -> SuppressionRecord:
        self.s.add(record)
        self.s.flush()
        return record

    def all(self) -> list[SuppressionRecord]:
        return list(
            self.s.scalars(select(SuppressionRecord).order_by(SuppressionRecord.created_at.desc()))
        )
