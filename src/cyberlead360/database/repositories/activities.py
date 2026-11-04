"""Activity, meeting and audit data access."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from cyberlead360.database.models import Activity, AuditEvent, Company, Contact, Meeting


class ActivityRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def get(self, activity_id: int) -> Activity | None:
        return self.s.get(Activity, activity_id)

    def add(self, activity: Activity) -> Activity:
        self.s.add(activity)
        self.s.flush()
        return activity

    def recent(
        self, limit: int = 50, company_id: int | None = None, types: list[str] | None = None
    ) -> list[tuple[Activity, str, str | None]]:
        stmt = (
            select(Activity, Company.company_name, Contact.first_name + " " + Contact.last_name)
            .join(Company, Company.id == Activity.company_id)
            .outerjoin(Contact, Contact.id == Activity.contact_id)
        )
        if company_id:
            stmt = stmt.where(Activity.company_id == company_id)
        if types:
            stmt = stmt.where(Activity.activity_type.in_(types))
        stmt = stmt.order_by(Activity.occurred_at.desc(), Activity.id.desc()).limit(limit)
        return [(r[0], r[1], r[2]) for r in self.s.execute(stmt)]

    def open_follow_ups(self, until: datetime | None = None) -> list[tuple[Activity, str]]:
        stmt = (
            select(Activity, Company.company_name)
            .join(Company, Company.id == Activity.company_id)
            .where(
                Activity.follow_up_at.is_not(None),
                Activity.follow_up_done.is_(False),
                Company.archived_at.is_(None),
            )
        )
        if until is not None:
            stmt = stmt.where(Activity.follow_up_at <= until)
        stmt = stmt.order_by(Activity.follow_up_at)
        return [(r[0], r[1]) for r in self.s.execute(stmt)]

    def for_contact(self, contact_id: int) -> list[Activity]:
        return list(self.s.scalars(select(Activity).where(Activity.contact_id == contact_id)))


class MeetingRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def get(self, meeting_id: int) -> Meeting | None:
        return self.s.get(Meeting, meeting_id)

    def add(self, meeting: Meeting) -> Meeting:
        self.s.add(meeting)
        self.s.flush()
        return meeting

    def list(self, company_id: int | None = None) -> list[tuple[Meeting, str]]:
        stmt = select(Meeting, Company.company_name).join(Company)
        if company_id:
            stmt = stmt.where(Meeting.company_id == company_id)
        stmt = stmt.order_by(Meeting.scheduled_at.desc())
        return [(r[0], r[1]) for r in self.s.execute(stmt)]


class AuditRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def record(
        self,
        entity_type: str,
        entity_id: int | None,
        action: str,
        actor: str,
        details: dict[str, object] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor=actor,
            details=details or {},
        )
        self.s.add(event)
        return event

    def recent(self, limit: int = 100, entity_type: str | None = None) -> list[AuditEvent]:
        stmt = select(AuditEvent)
        if entity_type:
            stmt = stmt.where(AuditEvent.entity_type == entity_type)
        return list(
            self.s.scalars(
                stmt.order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc()).limit(limit)
            )
        )
