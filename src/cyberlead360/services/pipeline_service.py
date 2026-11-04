"""CRM pipeline: prospect stages, opportunities, activities, follow-ups and meetings.

Prospect stage (company lifecycle) and opportunity stage (deal lifecycle) are
separate state machines. Opportunity changes *synchronize* the company stage
forward when that is consistent; they never move it backwards silently.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from cyberlead360.database.models import Activity, Company, Meeting, Opportunity
from cyberlead360.database.repositories.activities import (
    ActivityRepository,
    AuditRepository,
    MeetingRepository,
)
from cyberlead360.database.repositories.companies import CompanyRepository
from cyberlead360.database.repositories.contacts import ContactRepository
from cyberlead360.database.repositories.opportunities import OpportunityRepository
from cyberlead360.domain.enums import (
    ActivityDirection,
    ActivityType,
    MeetingStatus,
    OpportunityStage,
    ProspectStage,
)
from cyberlead360.domain.exceptions import NotFoundError, ValidationFailedError
from cyberlead360.domain.pipeline_rules import (
    OPPORTUNITY_TO_PROSPECT_STAGE,
    PROSPECT_TRANSITIONS,
    validate_opportunity_transition,
    validate_prospect_transition,
)
from cyberlead360.domain.schemas import ActivityCreate, MeetingCreate, OpportunityCreate
from cyberlead360.services.compliance_service import ComplianceService
from cyberlead360.utils.date_utils import ensure_utc, utcnow

_TOUCH_TO_STAGE = {
    ActivityType.EMAIL_SENT: ProspectStage.CONTACTED,
    ActivityType.CALL: ProspectStage.CONTACTED,
    ActivityType.LINKEDIN_MESSAGE: ProspectStage.CONTACTED,
    ActivityType.REPLY_RECEIVED: ProspectStage.REPLIED,
}


class PipelineService:
    def __init__(self, session: Session, actor: str) -> None:
        self.s = session
        self.actor = actor
        self.companies = CompanyRepository(session)
        self.contacts = ContactRepository(session)
        self.opps = OpportunityRepository(session)
        self.activities = ActivityRepository(session)
        self.meetings = MeetingRepository(session)
        self.audit = AuditRepository(session)
        self.compliance = ComplianceService(session, actor)

    # ------------------------------------------------------------------ helpers
    def _company(self, company_id: int) -> Company:
        company = self.companies.get(company_id)
        if company is None:
            raise NotFoundError("Company", company_id)
        return company

    def _check_contact(self, company_id: int, contact_id: int | None) -> None:
        if contact_id is None:
            return
        contact = self.contacts.get(contact_id)
        if contact is None or contact.company_id != company_id:
            raise ValidationFailedError("The contact must belong to the selected company.")

    def _apply_stage(
        self, company: Company, target: ProspectStage, note: str, at: datetime | None = None
    ) -> None:
        previous = company.prospect_stage
        when = at or utcnow()
        company.prospect_stage = target.value
        company.stage_changed_at = when
        company.highest_stage_order = max(company.highest_stage_order, target.order)
        if target == ProspectStage.ARCHIVED:
            company.archived_at = when
        elif previous == ProspectStage.ARCHIVED.value:
            company.archived_at = None
        self.activities.add(
            Activity(
                company_id=company.id,
                activity_type=ActivityType.STAGE_CHANGE.value,
                direction=ActivityDirection.INTERNAL.value,
                subject=f"{ProspectStage(previous).label} → {target.label}",
                notes=note or None,
                occurred_at=when,
                created_by=self.actor,
            )
        )
        self.audit.record(
            "company",
            company.id,
            "stage_changed",
            self.actor,
            {"from": previous, "to": target.value},
        )

    def _sync_forward(
        self, company: Company, target: ProspectStage, note: str, at: datetime | None = None
    ) -> bool:
        """Advance the company stage if consistent; never moves it backwards."""
        current = company.stage
        if current == target or company.is_archived:
            return False
        if target in PROSPECT_TRANSITIONS[current] or (
            current not in (ProspectStage.LOST, ProspectStage.ARCHIVED)
            and target.order > current.order
        ):
            self._apply_stage(company, target, note, at)
            return True
        return False

    # ------------------------------------------------------------------ prospect stage
    def change_stage(self, company_id: int, target: ProspectStage, note: str = "") -> Company:
        company = self._company(company_id)
        validate_prospect_transition(company.stage, target)
        # Deal stages must be backed by an opportunity record (open, or won for WON).
        has_open = bool(self.opps.open_for_company(company_id))
        has_won = any(o.stage == OpportunityStage.WON.value for o in company.opportunities)
        needs_opp = target in (ProspectStage.WON, ProspectStage.PROPOSAL_SENT)
        if needs_opp and not (has_open or (target == ProspectStage.WON and has_won)):
            raise ValidationFailedError(
                f"'{target.label}' requires an opportunity. Create or update one in the "
                "Opportunities section — the company stage will follow."
            )
        if target == ProspectStage.ARCHIVED and self.opps.open_for_company(company_id):
            raise ValidationFailedError("Close the open opportunities before archiving.")
        self._apply_stage(company, target, note)
        return company

    # ------------------------------------------------------------------ opportunities
    def create_opportunity(self, data: OpportunityCreate) -> Opportunity:
        company = self._company(data.company_id)
        if company.is_archived:
            raise ValidationFailedError("Restore the company before creating an opportunity.")
        self._check_contact(company.id, data.primary_contact_id)
        opp = self.opps.add(
            Opportunity(
                company_id=company.id,
                primary_contact_id=data.primary_contact_id,
                name=data.name,
                service_line=data.service_line.value,
                stage=OpportunityStage.OPEN.value,
                estimated_value=data.estimated_value,
                currency=data.currency,
                probability=data.probability,
                expected_close_date=data.expected_close_date,
                next_action=data.next_action,
                next_action_date=data.next_action_date,
            )
        )
        self.audit.record("opportunity", opp.id, "created", self.actor, {"company_id": company.id})
        self._sync_forward(company, ProspectStage.OPPORTUNITY_OPEN, f"Opportunity #{opp.id} opened")
        return opp

    def move_opportunity(
        self,
        opportunity_id: int,
        target: OpportunityStage,
        reason: str | None = None,
        at: datetime | None = None,
    ) -> Opportunity:
        opp = self.opps.get(opportunity_id)
        if opp is None:
            raise NotFoundError("Opportunity", opportunity_id)
        validate_opportunity_transition(OpportunityStage(opp.stage), target)
        if target == OpportunityStage.LOST and not (reason and reason.strip()):
            raise ValidationFailedError("A reason is required when an opportunity is lost.")
        when = at or utcnow()
        previous = opp.stage
        opp.stage = target.value
        if target.is_closed:
            opp.closed_at = when
            opp.won_lost_reason = (reason or "").strip() or None
            opp.probability = 100 if target == OpportunityStage.WON else 0
        else:
            opp.closed_at = None
        self.audit.record(
            "opportunity",
            opp.id,
            "stage_changed",
            self.actor,
            {"from": previous, "to": target.value},
        )
        company = self._company(opp.company_id)
        company_target = OPPORTUNITY_TO_PROSPECT_STAGE[target]
        others_open = [o for o in self.opps.open_for_company(company.id) if o.id != opp.id]
        if target == OpportunityStage.LOST and others_open:
            return opp  # other deals still running: keep company stage
        if target == OpportunityStage.LOST:
            if (
                company.stage in PROSPECT_TRANSITIONS
                and company_target in PROSPECT_TRANSITIONS[company.stage]
            ):
                self._apply_stage(company, company_target, f"Opportunity #{opp.id} lost", when)
        else:
            self._sync_forward(
                company, company_target, f"Opportunity #{opp.id}: {target.value}", when
            )
        return opp

    def update_opportunity(
        self,
        opportunity_id: int,
        *,
        estimated_value: float | None = None,
        probability: int | None = None,
        next_action: str | None = None,
        next_action_date: object = None,
        expected_close_date: object = None,
    ) -> Opportunity:
        opp = self.opps.get(opportunity_id)
        if opp is None:
            raise NotFoundError("Opportunity", opportunity_id)
        if OpportunityStage(opp.stage).is_closed:
            raise ValidationFailedError("Closed opportunities cannot be edited.")
        if probability is not None and not 0 <= probability <= 100:
            raise ValidationFailedError("Probability must be between 0 and 100.")
        if estimated_value is not None and estimated_value < 0:
            raise ValidationFailedError("Value cannot be negative.")
        from decimal import Decimal

        if estimated_value is not None:
            opp.estimated_value = Decimal(str(round(estimated_value, 2)))
        if probability is not None:
            opp.probability = probability
        opp.next_action = next_action
        opp.next_action_date = next_action_date  # type: ignore[assignment]
        opp.expected_close_date = expected_close_date  # type: ignore[assignment]
        self.audit.record("opportunity", opp.id, "updated", self.actor)
        return opp

    # ------------------------------------------------------------------ activities
    def log_activity(self, data: ActivityCreate, *, auto_advance: bool = True) -> Activity:
        company = self._company(data.company_id)
        self._check_contact(company.id, data.contact_id)
        activity_type = ActivityType(data.activity_type)
        if activity_type == ActivityType.STAGE_CHANGE:
            raise ValidationFailedError("Stage changes are recorded through the pipeline.")
        if activity_type.is_outbound_touch and data.contact_id:
            contact = self.contacts.get(data.contact_id)
            assert contact is not None
            self.compliance.assert_contactable(contact)
        occurred = ensure_utc(data.occurred_at) or utcnow()
        direction = data.direction
        if activity_type == ActivityType.REPLY_RECEIVED:
            direction = ActivityDirection.INBOUND
        elif activity_type == ActivityType.NOTE:
            direction = ActivityDirection.INTERNAL
        activity = self.activities.add(
            Activity(
                company_id=company.id,
                contact_id=data.contact_id,
                opportunity_id=data.opportunity_id,
                activity_type=activity_type.value,
                direction=direction.value,
                subject=data.subject,
                notes=data.notes,
                occurred_at=occurred,
                follow_up_at=ensure_utc(data.follow_up_at),
                created_by=self.actor,
            )
        )
        if company.last_activity_at is None or occurred > company.last_activity_at:
            company.last_activity_at = occurred
        if data.contact_id and activity_type.is_outbound_touch:
            contact = self.contacts.get(data.contact_id)
            if contact and (
                contact.last_contacted_at is None or occurred > contact.last_contacted_at
            ):
                contact.last_contacted_at = occurred
        if auto_advance and activity_type in _TOUCH_TO_STAGE:
            target = _TOUCH_TO_STAGE[activity_type]
            if company.stage.order < target.order:
                self._sync_forward(company, target, f"Auto: {activity_type.value} logged", occurred)
        return activity

    def complete_follow_up(self, activity_id: int) -> Activity:
        activity = self.activities.get(activity_id)
        if activity is None:
            raise NotFoundError("Activity", activity_id)
        activity.follow_up_done = True
        self.audit.record("activity", activity.id, "follow_up_done", self.actor)
        return activity

    # ------------------------------------------------------------------ meetings
    def schedule_meeting(self, data: MeetingCreate) -> Meeting:
        """Record a meeting. No calendar invitation is sent by the application."""
        company = self._company(data.company_id)
        self._check_contact(company.id, data.contact_id)
        if data.contact_id:
            contact = self.contacts.get(data.contact_id)
            assert contact is not None
            self.compliance.assert_contactable(contact)
        scheduled = ensure_utc(data.scheduled_at)
        assert scheduled is not None
        meeting = self.meetings.add(
            Meeting(
                company_id=company.id,
                contact_id=data.contact_id,
                opportunity_id=data.opportunity_id,
                scheduled_at=scheduled,
                duration_minutes=data.duration_minutes,
                meeting_type=data.meeting_type,
                location=data.location,
                notes=data.notes,
                status=data.status.value,
            )
        )
        self.activities.add(
            Activity(
                company_id=company.id,
                contact_id=data.contact_id,
                opportunity_id=data.opportunity_id,
                activity_type=ActivityType.MEETING.value,
                direction=ActivityDirection.OUTBOUND.value,
                subject=f"Meeting scheduled ({data.meeting_type})",
                occurred_at=utcnow(),
                created_by=self.actor,
            )
        )
        if company.stage.order < ProspectStage.MEETING_SCHEDULED.order:
            self._sync_forward(
                company, ProspectStage.MEETING_SCHEDULED, f"Meeting #{meeting.id} scheduled"
            )
        self.audit.record("meeting", meeting.id, "scheduled", self.actor)
        return meeting

    def set_meeting_status(self, meeting_id: int, status: MeetingStatus) -> Meeting:
        meeting = self.meetings.get(meeting_id)
        if meeting is None:
            raise NotFoundError("Meeting", meeting_id)
        meeting.status = status.value
        self.audit.record(
            "meeting", meeting.id, "status_changed", self.actor, {"status": status.value}
        )
        return meeting
