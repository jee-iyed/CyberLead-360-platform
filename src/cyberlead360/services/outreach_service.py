"""Outreach drafts: generation (LLM or template), editing and human approval.

The application NEVER sends messages. A human approves a draft, sends it from
their own mailbox / LinkedIn, then marks it "sent manually", which logs the
activity in the CRM.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from cyberlead360.config.settings import Settings
from cyberlead360.database.models import OutreachDraft
from cyberlead360.database.repositories.activities import AuditRepository
from cyberlead360.database.repositories.companies import CompanyRepository
from cyberlead360.database.repositories.contacts import ContactRepository, SuppressionRepository
from cyberlead360.database.repositories.intelligence import IntelligenceRepository
from cyberlead360.domain.enums import (
    ActivityDirection,
    ActivityType,
    DraftStatus,
    GenerationMode,
    MessageType,
    ServiceLine,
)
from cyberlead360.domain.exceptions import (
    AIProviderError,
    NotFoundError,
    SuppressedContactError,
    ValidationFailedError,
)
from cyberlead360.domain.schemas import ActivityCreate, OutreachDraftOutput, OutreachRequest
from cyberlead360.integrations.llm.base import LLMProvider
from cyberlead360.services.ai_service import (
    FIRST_NAME_PLACEHOLDER,
    GUARDRAIL_RULES,
    AIRunMeta,
    AIService,
    build_context,
    check_citations,
    deterministic_analysis,
    find_risky_claims,
    render_context_block,
)
from cyberlead360.services.compliance_service import ComplianceService
from cyberlead360.services.outreach_templates import render_template
from cyberlead360.utils.date_utils import utcnow


class OutreachService:
    def __init__(
        self, session: Session, actor: str, settings: Settings, provider: LLMProvider | None
    ) -> None:
        self.s = session
        self.actor = actor
        self.settings = settings
        self.ai = AIService(settings, provider)
        self.repo = IntelligenceRepository(session)
        self.contacts = ContactRepository(session)
        self.companies = CompanyRepository(session)
        self.compliance = ComplianceService(session, actor)
        self.audit = AuditRepository(session)

    def _draft(self, draft_id: int) -> OutreachDraft:
        draft = self.repo.get_draft(draft_id)
        if draft is None:
            raise NotFoundError("Draft", draft_id)
        return draft

    def _check_permitted(self, company_id: int, contact_id: int | None) -> None:
        company = self.companies.get(company_id)
        if company is None:
            raise NotFoundError("Company", company_id)
        if company.normalized_domain and SuppressionRepository(self.s).by_domain(
            company.normalized_domain
        ):
            raise SuppressedContactError("Outreach blocked: the company domain is suppressed.")
        if contact_id is not None:
            contact = self.contacts.get(contact_id)
            if contact is None or contact.company_id != company_id:
                raise ValidationFailedError("The contact must belong to the selected company.")
            self.compliance.assert_contactable(contact)

    def generate(self, req: OutreachRequest) -> OutreachDraft:
        self._check_permitted(req.company_id, req.contact_id)
        ctx = build_context(self.s, req.company_id)
        service = req.service_focus or self._default_service(ctx)
        contact = self.contacts.get(req.contact_id) if req.contact_id else None

        subject, body, evidence, warnings = None, "", [], []
        meta = AIRunMeta(mode=GenerationMode.TEMPLATE)
        if req.use_llm and self.ai.llm_available:
            try:
                out, meta = self._generate_llm(
                    req, ctx, service, contact.job_title if contact else None
                )
                subject, body = out.subject, out.body
                evidence, cite_warn = check_citations(out.evidence_fact_ids, ctx.fact_ids)
                warnings = [*meta.warnings, *cite_warn, *out.personalization_notes]
            except AIProviderError as exc:
                warnings.append(f"LLM generation failed ({exc}); deterministic template used.")
                meta = AIRunMeta(mode=GenerationMode.TEMPLATE)
        elif req.use_llm:
            warnings.append("No LLM configured: deterministic template mode.")

        if meta.mode == GenerationMode.TEMPLATE:
            tpl = render_template(
                ctx,
                req.message_type,
                req.tone,
                req.language,
                service,
                req.sender_name,
                req.sender_company,
            )
            subject, body, evidence = tpl.subject, tpl.body, tpl.evidence_fact_ids
            warnings.extend(tpl.notes)

        first_name = contact.first_name if contact else ""
        body = body.replace(FIRST_NAME_PLACEHOLDER, first_name).replace(" ,", ",")
        if not contact:
            warnings.append("No contact selected: greeting left generic — edit before use.")

        draft = self.repo.add_draft(
            OutreachDraft(
                company_id=req.company_id,
                contact_id=req.contact_id,
                message_type=req.message_type.value,
                language=req.language.value,
                tone=req.tone.value,
                subject=subject,
                body=body,
                generation_mode=meta.mode.value,
                provider=meta.provider,
                model=meta.model,
                evidence_fact_ids=evidence,
                warnings=warnings,
                input_tokens=meta.input_tokens,
                output_tokens=meta.output_tokens,
                status=DraftStatus.DRAFT.value,
            )
        )
        self.audit.record(
            "outreach_draft",
            draft.id,
            "generated",
            self.actor,
            {"mode": meta.mode.value, "company_id": req.company_id},
        )
        return draft

    @staticmethod
    def _default_service(ctx) -> ServiceLine:  # type: ignore[no-untyped-def]
        analysis = deterministic_analysis(ctx)
        return (
            analysis.suggestions[0].service_line
            if analysis.suggestions
            else ServiceLine.SECURITY_AWARENESS
        )

    def _generate_llm(
        self,
        req: OutreachRequest,
        ctx,
        service: ServiceLine,
        job_title: str | None,  # type: ignore[no-untyped-def]
    ) -> tuple[OutreachDraftOutput, AIRunMeta]:
        lang = "French" if req.language.value == "fr" else "English"
        limit = (
            "at most 300 characters, no subject"
            if req.message_type == MessageType.LINKEDIN_CONNECTION
            else "120-180 words with a short subject line"
        )
        system = (
            "You write first drafts of B2B outreach messages for a cybersecurity services "
            "firm. A human will review and edit every draft before anything is sent.\n"
            + GUARDRAIL_RULES
        )
        recipient = f"Recipient role: {job_title}." if job_title else "Recipient role: unknown."
        user = (
            render_context_block(ctx, self.settings.llm_max_input_chars)
            + f"\n\nTask: write a {req.message_type.label.lower()} in {lang}, tone "
            f"'{req.tone.value}', {limit}. Focus service: {service.label}. {recipient} "
            f"Sender: {req.sender_name}, {req.sender_company}. Greet with "
            f"'{FIRST_NAME_PLACEHOLDER}'. Reference at most two facts and list their ids in "
            "evidence_fact_ids."
        )
        out, meta = self.ai.call_structured(system, user, OutreachDraftOutput)
        risky = find_risky_claims(f"{out.subject or ''} {out.body}")
        if risky:
            raise AIProviderError(f"draft contained unsupported risk claims {risky}")
        if req.message_type == MessageType.LINKEDIN_CONNECTION and len(out.body) > 300:
            out.body = out.body[:300]
            meta.warnings.append("LinkedIn note truncated to 300 characters.")
        return out, meta

    # ------------------------------------------------------------------ review workflow
    def edit(self, draft_id: int, subject: str | None, body: str) -> OutreachDraft:
        draft = self._draft(draft_id)
        if draft.status != DraftStatus.DRAFT.value:
            raise ValidationFailedError("Only drafts in 'draft' status can be edited.")
        body = body.strip()
        if len(body) < 20:
            raise ValidationFailedError("The message body is too short.")
        draft.subject = (subject or "").strip() or None
        draft.body = body[:4000]
        risky = find_risky_claims(f"{draft.subject or ''} {draft.body}")
        warnings = [w for w in draft.warnings if not w.startswith("Review wording:")]
        if risky:
            warnings.append(
                f"Review wording: terms {risky} may imply an unverified security weakness."
            )
        draft.warnings = warnings
        self.audit.record("outreach_draft", draft.id, "edited", self.actor)
        return draft

    def approve(self, draft_id: int) -> OutreachDraft:
        draft = self._draft(draft_id)
        if draft.status != DraftStatus.DRAFT.value:
            raise ValidationFailedError("Only drafts can be approved.")
        if FIRST_NAME_PLACEHOLDER in draft.body:
            raise ValidationFailedError("Replace the {{first_name}} placeholder before approving.")
        self._check_permitted(draft.company_id, draft.contact_id)
        draft.status = DraftStatus.APPROVED.value
        draft.approved_at = utcnow()
        draft.approved_by = self.actor
        self.audit.record("outreach_draft", draft.id, "approved", self.actor)
        return draft

    def reject(self, draft_id: int) -> OutreachDraft:
        draft = self._draft(draft_id)
        if draft.status not in (DraftStatus.DRAFT.value, DraftStatus.APPROVED.value):
            raise ValidationFailedError("This draft can no longer be rejected.")
        draft.status = DraftStatus.REJECTED.value
        self.audit.record("outreach_draft", draft.id, "rejected", self.actor)
        return draft

    def mark_sent_manually(self, draft_id: int) -> OutreachDraft:
        """Record that a human sent the approved message outside the application."""
        from cyberlead360.services.pipeline_service import PipelineService

        draft = self._draft(draft_id)
        if draft.status != DraftStatus.APPROVED.value:
            raise ValidationFailedError("Approve the draft before marking it as sent.")
        self._check_permitted(draft.company_id, draft.contact_id)
        activity_type = (
            ActivityType.LINKEDIN_MESSAGE
            if draft.message_type == MessageType.LINKEDIN_CONNECTION.value
            else ActivityType.EMAIL_SENT
        )
        PipelineService(self.s, self.actor).log_activity(
            ActivityCreate(
                company_id=draft.company_id,
                contact_id=draft.contact_id,
                activity_type=activity_type,
                direction=ActivityDirection.OUTBOUND,
                subject=(draft.subject or MessageType(draft.message_type).label)[:200],
                notes=f"Sent manually from approved draft #{draft.id}.",
            )
        )
        draft.status = DraftStatus.SENT_MANUALLY.value
        self.audit.record("outreach_draft", draft.id, "sent_manually", self.actor)
        return draft
