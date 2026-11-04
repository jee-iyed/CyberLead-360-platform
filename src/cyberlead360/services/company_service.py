"""Company use cases: create, update, archive, deduplicate and merge.

Duplicate policy
----------------
* Same normalized domain  → *definite* duplicate, creation is refused.
* Same normalized name, or name similarity ≥ 0.88 in the same country
  → *possible* duplicate, creation requires explicit human confirmation.
Records are never overwritten silently: merges are explicit, field-level,
audited, and the duplicate row is archived (``merged_into_id``), not deleted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from cyberlead360.config.logging import get_logger
from cyberlead360.database.models import (
    Activity,
    Company,
    CompanyFact,
    CompanySource,
    Contact,
    Meeting,
    Opportunity,
    OutreachDraft,
    ScoringResult,
)
from cyberlead360.database.repositories.activities import AuditRepository
from cyberlead360.database.repositories.companies import CompanyFilters, CompanyRepository
from cyberlead360.database.repositories.opportunities import OpportunityRepository
from cyberlead360.domain.enums import ProspectStage
from cyberlead360.domain.exceptions import (
    DuplicateCompanyError,
    NotFoundError,
    ValidationFailedError,
)
from cyberlead360.domain.schemas import CompanyCreate, CompanyUpdate
from cyberlead360.utils.date_utils import utcnow
from cyberlead360.utils.normalization import (
    employee_range,
    name_similarity,
    normalize_company_name,
    normalize_domain,
)

log = get_logger("company_service")

SIMILARITY_THRESHOLD = 0.88
MERGEABLE_FIELDS = (
    "website",
    "industry",
    "subindustry",
    "country",
    "city",
    "employee_count",
    "description",
    "cybersecurity_interest",
    "owner",
)


@dataclass(frozen=True)
class DuplicateCandidate:
    company_id: int
    company_name: str
    certainty: Literal["definite", "possible"]
    reason: str
    similarity: float


@dataclass(frozen=True)
class DuplicatePair:
    first_id: int
    first_name: str
    second_id: int
    second_name: str
    certainty: Literal["definite", "possible"]
    reason: str
    similarity: float


class CompanyService:
    def __init__(self, session: Session, actor: str) -> None:
        self.s = session
        self.actor = actor
        self.repo = CompanyRepository(session)
        self.audit = AuditRepository(session)

    # ------------------------------------------------------------------ queries
    def get(self, company_id: int) -> Company:
        company = self.repo.get(company_id)
        if company is None:
            raise NotFoundError("Company", company_id)
        return company

    def search(self, filters: CompanyFilters) -> list[tuple[Company, int | None, str | None]]:
        return self.repo.search(filters)

    # ------------------------------------------------------------------ duplicates
    def find_duplicates(
        self,
        company_name: str,
        website: str | None,
        country: str | None,
        exclude_id: int | None = None,
    ) -> list[DuplicateCandidate]:
        candidates: list[DuplicateCandidate] = []
        domain = normalize_domain(website) if website else None
        norm = normalize_company_name(company_name)
        seen: set[int] = set()
        if domain:
            match = self.repo.by_domain(domain)
            if match and match.id != exclude_id:
                candidates.append(
                    DuplicateCandidate(
                        match.id, match.company_name, "definite", f"Same domain '{domain}'", 1.0
                    )
                )
                seen.add(match.id)
        for cid, other_norm, other_country, _dom in self.repo.all_active_name_index():
            if cid in seen or cid == exclude_id:
                continue
            if other_norm == norm:
                candidates.append(
                    DuplicateCandidate(
                        cid, self.get(cid).company_name, "possible", "Same normalized name", 1.0
                    )
                )
                continue
            same_country = country is None or other_country is None or other_country == country
            if same_country and other_norm[:1] == norm[:1]:
                ratio = name_similarity(norm, other_norm)
                if ratio >= SIMILARITY_THRESHOLD:
                    candidates.append(
                        DuplicateCandidate(
                            cid,
                            self.get(cid).company_name,
                            "possible",
                            f"Similar name ({ratio:.0%})",
                            round(ratio, 2),
                        )
                    )
        return candidates

    def duplicate_report(self) -> list[DuplicatePair]:
        """Scan active companies for possible duplicates (blocking on first letter)."""
        rows = [r for r in self.repo.all_active_name_index()]
        active = {c for c in self.repo.active_ids()}
        rows = [r for r in rows if r[0] in active]
        names = {c.id: c.company_name for c in self.s.scalars(select(Company))}
        blocks: dict[str, list[tuple[int, str, str | None, str | None]]] = {}
        for row in rows:
            blocks.setdefault(row[1][:1], []).append(row)
        pairs: list[DuplicatePair] = []
        for block in blocks.values():
            for i, a in enumerate(block):
                for b in block[i + 1 :]:
                    if a[1] == b[1]:
                        reason, ratio = "Same normalized name", 1.0
                    else:
                        ratio = name_similarity(a[1], b[1])
                        if ratio < SIMILARITY_THRESHOLD or (a[2] and b[2] and a[2] != b[2]):
                            continue
                        reason = f"Similar name ({ratio:.0%})"
                    pairs.append(
                        DuplicatePair(
                            a[0],
                            names[a[0]],
                            b[0],
                            names[b[0]],
                            "possible",
                            reason,
                            round(ratio, 2),
                        )
                    )
        return sorted(pairs, key=lambda p: -p.similarity)

    # ------------------------------------------------------------------ commands
    def create(
        self,
        data: CompanyCreate,
        *,
        confirm_possible_duplicate: bool = False,
        source_label: str = "manual",
    ) -> Company:
        dups = self.find_duplicates(data.company_name, data.website, data.country)
        definite = [d for d in dups if d.certainty == "definite"]
        if definite:
            d = definite[0]
            raise DuplicateCompanyError(
                f"'{d.company_name}' (#{d.company_id}) already uses this domain. "
                "Edit or merge the existing record instead.",
                existing_id=d.company_id,
            )
        if dups and not confirm_possible_duplicate:
            names = ", ".join(f"{d.company_name} (#{d.company_id}, {d.reason})" for d in dups)
            raise DuplicateCompanyError(
                f"Possible duplicate of: {names}. Confirm to create anyway.",
                existing_id=dups[0].company_id,
            )
        company = Company(
            company_name=data.company_name,
            normalized_name=normalize_company_name(data.company_name),
            website=data.website,
            normalized_domain=normalize_domain(data.website),
            industry=data.industry.value if data.industry else None,
            subindustry=data.subindustry,
            country=data.country,
            city=data.city,
            employee_count=data.employee_count,
            employee_range=employee_range(data.employee_count),
            description=data.description,
            cybersecurity_interest=data.cybersecurity_interest,
            owner=data.owner or self.actor,
            prospect_stage=ProspectStage.NEW.value,
            highest_stage_order=ProspectStage.NEW.order,
            stage_changed_at=utcnow(),
        )
        self.repo.add(company)
        self.audit.record(
            "company",
            company.id,
            "created",
            self.actor,
            {"via": source_label, "possible_duplicates": [d.company_id for d in dups]},
        )
        self._rescore(company.id)
        log.info("company created", extra={"company_id": company.id})
        return company

    def update(self, company_id: int, data: CompanyUpdate) -> Company:
        company = self.get(company_id)
        if company.is_archived:
            raise ValidationFailedError("Archived companies must be restored before editing.")
        new_domain = normalize_domain(data.website)
        if new_domain and new_domain != company.normalized_domain:
            other = self.repo.by_domain(new_domain)
            if other and other.id != company.id:
                raise DuplicateCompanyError(
                    f"Domain '{new_domain}' is already used by '{other.company_name}' "
                    f"(#{other.id}). Consider merging.",
                    existing_id=other.id,
                )
        values = data.model_dump()
        values["industry"] = data.industry.value if data.industry else None
        values["qualification_status"] = data.qualification_status.value
        changed: list[str] = []
        for key, value in values.items():
            if getattr(company, key) != value:
                setattr(company, key, value)
                changed.append(key)
        if "company_name" in changed:
            company.normalized_name = normalize_company_name(company.company_name)
        if "website" in changed:
            company.normalized_domain = new_domain
        if "employee_count" in changed:
            company.employee_range = employee_range(company.employee_count)
        if changed:
            self.audit.record("company", company.id, "updated", self.actor, {"fields": changed})
            self.s.flush()
            self._rescore(company.id)
        return company

    def archive(self, company_id: int, reason: str) -> Company:
        company = self.get(company_id)
        if company.is_archived:
            return company
        if OpportunityRepository(self.s).open_for_company(company_id):
            raise ValidationFailedError(
                "Close (win/lose) the company's open opportunities before archiving it."
            )
        previous = company.prospect_stage
        company.archived_at = utcnow()
        company.prospect_stage = ProspectStage.ARCHIVED.value
        company.stage_changed_at = company.archived_at
        self.audit.record(
            "company",
            company.id,
            "archived",
            self.actor,
            {"previous_stage": previous, "reason": reason[:200]},
        )
        return company

    def restore(self, company_id: int) -> Company:
        company = self.get(company_id)
        if company.merged_into_id:
            raise ValidationFailedError("A merged record cannot be restored.")
        company.archived_at = None
        company.prospect_stage = ProspectStage.NEW.value
        company.stage_changed_at = utcnow()
        self.audit.record("company", company.id, "restored", self.actor)
        return company

    def merge(
        self,
        primary_id: int,
        duplicate_id: int,
        take_from_duplicate: list[str] | None = None,
    ) -> Company:
        """Merge ``duplicate`` into ``primary`` inside one transaction.

        * Empty primary fields are filled from the duplicate.
        * Fields listed in ``take_from_duplicate`` are explicitly overwritten.
        * All child records are re-pointed to the primary.
        * The duplicate is archived with ``merged_into_id`` (never deleted).
        """
        if primary_id == duplicate_id:
            raise ValidationFailedError("Cannot merge a company into itself.")
        primary, dup = self.get(primary_id), self.get(duplicate_id)
        if dup.merged_into_id:
            raise ValidationFailedError("The duplicate has already been merged.")
        take = set(take_from_duplicate or [])
        unknown = take - set(MERGEABLE_FIELDS)
        if unknown:
            raise ValidationFailedError(f"Unknown merge fields: {sorted(unknown)}")

        filled: list[str] = []
        dup_domain = dup.normalized_domain
        for field in MERGEABLE_FIELDS:
            dup_value = getattr(dup, field)
            if dup_value is None:
                continue
            if field in take or getattr(primary, field) in (None, ""):
                if field == "website":
                    # Release the unique domain on the duplicate first.
                    dup.normalized_domain = None
                    self.s.flush()
                    primary.normalized_domain = dup_domain
                setattr(primary, field, dup_value)
                filled.append(field)
        primary.employee_range = employee_range(primary.employee_count)

        self._merge_contacts(primary.id, dup.id)
        for model in (CompanySource, CompanyFact, Activity, Opportunity, Meeting, OutreachDraft):
            self.s.execute(
                update(model).where(model.company_id == dup.id).values(company_id=primary.id)
            )
        self.s.execute(
            update(ScoringResult)
            .where(ScoringResult.company_id == dup.id)
            .values(company_id=primary.id, is_current=False)
        )
        if ProspectStage(dup.prospect_stage).order > ProspectStage(primary.prospect_stage).order:
            primary.highest_stage_order = max(primary.highest_stage_order, dup.highest_stage_order)

        dup.merged_into_id = primary.id
        dup.archived_at = utcnow()
        dup.prospect_stage = ProspectStage.ARCHIVED.value
        dup.normalized_domain = None
        self.audit.record(
            "company",
            primary.id,
            "merged",
            self.actor,
            {"merged_company_id": dup.id, "fields_taken": filled},
        )
        self.s.flush()
        self.s.expire_all()
        self._rescore(primary.id)
        return self.get(primary.id)

    def _merge_contacts(self, primary_id: int, dup_id: int) -> None:
        existing = {
            c.professional_email: c
            for c in self.s.scalars(select(Contact).where(Contact.company_id == primary_id))
            if c.professional_email
        }
        for contact in list(self.s.scalars(select(Contact).where(Contact.company_id == dup_id))):
            keeper = existing.get(contact.professional_email or "")
            if keeper is None:
                contact.company_id = primary_id
                continue
            # Same person on both records: keep the primary's contact, re-point history.
            for model, column in ((Activity, Activity.contact_id), (Meeting, Meeting.contact_id)):
                self.s.execute(
                    update(model).where(column == contact.id).values(contact_id=keeper.id)
                )
            self.s.execute(
                update(OutreachDraft)
                .where(OutreachDraft.contact_id == contact.id)
                .values(contact_id=keeper.id)
            )
            self.s.execute(
                update(Opportunity)
                .where(Opportunity.primary_contact_id == contact.id)
                .values(primary_contact_id=keeper.id)
            )
            self.s.delete(contact)
        self.s.flush()

    def _rescore(self, company_id: int) -> None:
        from cyberlead360.services.scoring_service import ScoringService

        ScoringService(self.s, self.actor).score_company(company_id)
