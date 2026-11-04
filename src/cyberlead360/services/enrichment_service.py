"""Company intelligence: sources, facts, human review and controlled retrieval.

Invariants
----------
* Every fact references a stored source (DB constraint + service check).
* Automatically extracted facts start as ``pending`` with ``low`` confidence and
  generic type; only a human reviewer can approve or reclassify them, and only
  approved facts influence scoring or AI generation.
* No citation is ever invented: a fact without a real source cannot be created.
"""

from __future__ import annotations

import hashlib

import pandas as pd
from sqlalchemy.orm import Session

from cyberlead360.config.settings import Settings
from cyberlead360.database.models import CompanyFact, CompanySource
from cyberlead360.database.repositories.activities import AuditRepository
from cyberlead360.database.repositories.companies import CompanyRepository
from cyberlead360.database.repositories.intelligence import IntelligenceRepository
from cyberlead360.domain.enums import (
    Confidence,
    FactType,
    ReviewStatus,
    SourceType,
    VerificationStatus,
)
from cyberlead360.domain.exceptions import (
    NotFoundError,
    RetrievalBlockedError,
    ValidationFailedError,
)
from cyberlead360.domain.schemas import FactCreate, SourceCreate
from cyberlead360.integrations.public_sources.html_extractor import extract_page
from cyberlead360.integrations.public_sources.safe_fetcher import SafeFetcher
from cyberlead360.utils.date_utils import freshness_label, utcnow
from cyberlead360.utils.normalization import normalize_domain


class EnrichmentService:
    def __init__(self, session: Session, actor: str) -> None:
        self.s = session
        self.actor = actor
        self.repo = IntelligenceRepository(session)
        self.companies = CompanyRepository(session)
        self.audit = AuditRepository(session)

    def _rescore(self, company_id: int) -> None:
        from cyberlead360.services.scoring_service import ScoringService

        ScoringService(self.s, self.actor).score_company(company_id)

    # ------------------------------------------------------------------ sources
    def add_source(self, data: SourceCreate) -> CompanySource:
        if self.companies.get(data.company_id) is None:
            raise NotFoundError("Company", data.company_id)
        if (
            data.source_type
            in (
                SourceType.OFFICIAL_WEBSITE,
                SourceType.PUBLIC_ANNOUNCEMENT,
                SourceType.PUBLIC_REGISTRY,
            )
            and not data.url
        ):
            raise ValidationFailedError("Public web sources must include their URL.")
        source = self.repo.add_source(
            CompanySource(
                company_id=data.company_id,
                source_type=data.source_type.value,
                title=data.title,
                url=data.url,
                publisher=data.publisher,
                published_at=data.published_at,
                notes=data.notes,
                collected_by=self.actor,
            )
        )
        self.audit.record(
            "source",
            source.id,
            "created",
            self.actor,
            {"company_id": data.company_id, "type": data.source_type.value},
        )
        return source

    def set_source_verification(self, source_id: int, status: VerificationStatus) -> CompanySource:
        source = self.repo.get_source(source_id)
        if source is None:
            raise NotFoundError("Source", source_id)
        source.verification_status = status.value
        self.audit.record(
            "source", source.id, "verification_changed", self.actor, {"status": status.value}
        )
        self._rescore(source.company_id)
        return source

    # ------------------------------------------------------------------ facts
    def add_fact(self, data: FactCreate, *, approve: bool = False) -> CompanyFact:
        source = self.repo.get_source(data.source_id)
        if source is None or source.company_id != data.company_id:
            raise ValidationFailedError("The fact's source must exist and belong to the company.")
        fact = self.repo.add_fact(
            CompanyFact(
                company_id=data.company_id,
                source_id=data.source_id,
                fact_type=data.fact_type.value,
                statement=data.statement,
                excerpt=data.excerpt,
                confidence=data.confidence.value,
                observed_at=data.observed_at or source.published_at or source.collected_at,
                review_status=(ReviewStatus.APPROVED if approve else ReviewStatus.PENDING).value,
                reviewed_at=utcnow() if approve else None,
                reviewed_by=self.actor if approve else None,
            )
        )
        self.audit.record(
            "fact",
            fact.id,
            "created",
            self.actor,
            {"company_id": data.company_id, "approved": approve},
        )
        if approve:
            self._rescore(data.company_id)
        return fact

    def review_fact(
        self,
        fact_id: int,
        decision: ReviewStatus,
        *,
        fact_type: FactType | None = None,
        confidence: Confidence | None = None,
    ) -> CompanyFact:
        fact = self.repo.get_fact(fact_id)
        if fact is None:
            raise NotFoundError("Fact", fact_id)
        if decision == ReviewStatus.PENDING:
            raise ValidationFailedError("Choose approve or reject.")
        fact.review_status = decision.value
        if fact_type is not None:
            fact.fact_type = fact_type.value
        if confidence is not None:
            fact.confidence = confidence.value
        fact.reviewed_at = utcnow()
        fact.reviewed_by = self.actor
        self.audit.record("fact", fact.id, f"review_{decision.value}", self.actor)
        self._rescore(fact.company_id)
        return fact

    def facts_dataframe(self, company_id: int, freshness_days: int) -> pd.DataFrame:
        rows = []
        now = utcnow()
        for fact, source in self.repo.facts_for(company_id):
            rows.append(
                {
                    "fact_id": fact.id,
                    "type": FactType(fact.fact_type).label,
                    "statement": fact.statement,
                    "confidence": fact.confidence,
                    "review": fact.review_status,
                    "observed": fact.observed_at,
                    "freshness": freshness_label(fact.observed_at, freshness_days, now),
                    "source_id": source.id,
                    "source": source.title,
                    "source_type": source.source_type,
                    "source_verification": source.verification_status,
                    "url": source.url,
                    "collected": source.collected_at,
                }
            )
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------ retrieval
    def retrieve_official_website(
        self,
        company_id: int,
        settings: Settings,
        url: str | None = None,
        fetcher: SafeFetcher | None = None,
    ) -> tuple[CompanySource, list[CompanyFact]]:
        """Fetch one public page, store it as an unverified source and create
        *pending* candidate facts from its visible text for human review."""
        if not settings.enable_web_retrieval and fetcher is None:
            raise RetrievalBlockedError(
                "Web retrieval is disabled. Set ENABLE_WEB_RETRIEVAL=true to allow it."
            )
        company = self.companies.get(company_id)
        if company is None:
            raise NotFoundError("Company", company_id)
        target = url or company.website
        if not target:
            raise ValidationFailedError("The company has no website to retrieve.")
        target_domain = normalize_domain(target)
        if not settings.retrieval_allow_any_public_host:
            allowed = company.normalized_domain
            if not allowed or not (
                target_domain == allowed or (target_domain or "").endswith("." + allowed)
            ):
                raise RetrievalBlockedError(
                    "Retrieval is restricted to the company's own website domain."
                )
        own_fetcher = fetcher is None
        fetcher = fetcher or SafeFetcher(
            user_agent=settings.retrieval_user_agent,
            timeout_seconds=settings.retrieval_timeout_seconds,
            max_bytes=settings.retrieval_max_bytes,
            min_interval_seconds=settings.retrieval_min_interval_seconds,
        )
        try:
            result = fetcher.fetch_html(target)
        finally:
            if own_fetcher:
                fetcher.close()
        page = extract_page(result.text)
        source = self.repo.add_source(
            CompanySource(
                company_id=company_id,
                source_type=SourceType.OFFICIAL_WEBSITE.value,
                title=(page.title or result.final_url)[:300],
                url=result.final_url,
                publisher=normalize_domain(result.final_url),
                collected_by=self.actor,
                content_sha256=hashlib.sha256(result.text.encode("utf-8")).hexdigest(),
                notes="Automatically retrieved. Verify before relying on it."
                + (" Content truncated at size limit." if result.truncated else ""),
            )
        )
        candidates = ([page.meta_description] if page.meta_description else []) + page.paragraphs[
            :5
        ]
        facts = [
            self.repo.add_fact(
                CompanyFact(
                    company_id=company_id,
                    source_id=source.id,
                    fact_type=FactType.BUSINESS_CONTEXT.value,
                    statement=text[:1000],
                    excerpt=text[:2000],
                    confidence=Confidence.LOW.value,
                    observed_at=source.collected_at,
                    review_status=ReviewStatus.PENDING.value,
                )
            )
            for text in candidates
        ]
        self.audit.record(
            "source",
            source.id,
            "retrieved",
            self.actor,
            {"company_id": company_id, "candidate_facts": len(facts)},
        )
        return source, facts
