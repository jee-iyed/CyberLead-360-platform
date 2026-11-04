"""Sources, facts, scoring rules/results and outreach drafts."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from cyberlead360.database.models import (
    CompanyFact,
    CompanySource,
    OutreachDraft,
    ScoringResult,
    ScoringRule,
)


class IntelligenceRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    # sources ---------------------------------------------------------------------
    def get_source(self, source_id: int) -> CompanySource | None:
        return self.s.get(CompanySource, source_id)

    def add_source(self, source: CompanySource) -> CompanySource:
        self.s.add(source)
        self.s.flush()
        return source

    def sources_for(self, company_id: int) -> list[CompanySource]:
        return list(
            self.s.scalars(
                select(CompanySource)
                .where(CompanySource.company_id == company_id)
                .order_by(CompanySource.collected_at.desc())
            )
        )

    # facts -------------------------------------------------------------------------
    def get_fact(self, fact_id: int) -> CompanyFact | None:
        return self.s.get(CompanyFact, fact_id)

    def add_fact(self, fact: CompanyFact) -> CompanyFact:
        self.s.add(fact)
        self.s.flush()
        return fact

    def facts_for(
        self, company_id: int, review_statuses: list[str] | None = None
    ) -> list[tuple[CompanyFact, CompanySource]]:
        stmt = (
            select(CompanyFact, CompanySource)
            .join(CompanySource, CompanySource.id == CompanyFact.source_id)
            .where(CompanyFact.company_id == company_id)
        )
        if review_statuses:
            stmt = stmt.where(CompanyFact.review_status.in_(review_statuses))
        stmt = stmt.order_by(CompanyFact.observed_at.desc(), CompanyFact.id)
        return [(r[0], r[1]) for r in self.s.execute(stmt)]

    # scoring -----------------------------------------------------------------------
    def active_rule(self) -> ScoringRule | None:
        return self.s.scalar(select(ScoringRule).where(ScoringRule.is_active.is_(True)))

    def rules(self) -> list[ScoringRule]:
        return list(self.s.scalars(select(ScoringRule).order_by(ScoringRule.version.desc())))

    def max_rule_version(self) -> int:
        rules = self.rules()
        return rules[0].version if rules else 0

    def add_rule(self, rule: ScoringRule) -> ScoringRule:
        self.s.add(rule)
        self.s.flush()
        return rule

    def deactivate_rules(self) -> None:
        self.s.execute(update(ScoringRule).values(is_active=False))

    def current_score(self, company_id: int) -> ScoringResult | None:
        return self.s.scalar(
            select(ScoringResult).where(
                ScoringResult.company_id == company_id, ScoringResult.is_current.is_(True)
            )
        )

    def score_history(self, company_id: int) -> list[ScoringResult]:
        return list(
            self.s.scalars(
                select(ScoringResult)
                .where(ScoringResult.company_id == company_id)
                .order_by(ScoringResult.calculated_at.desc(), ScoringResult.id.desc())
            )
        )

    def add_score(self, result: ScoringResult) -> ScoringResult:
        self.s.execute(
            update(ScoringResult)
            .where(ScoringResult.company_id == result.company_id)
            .values(is_current=False)
        )
        self.s.add(result)
        self.s.flush()
        return result

    # drafts ------------------------------------------------------------------------
    def get_draft(self, draft_id: int) -> OutreachDraft | None:
        return self.s.get(OutreachDraft, draft_id)

    def add_draft(self, draft: OutreachDraft) -> OutreachDraft:
        self.s.add(draft)
        self.s.flush()
        return draft

    def drafts(self, company_id: int | None = None) -> list[OutreachDraft]:
        stmt = select(OutreachDraft)
        if company_id:
            stmt = stmt.where(OutreachDraft.company_id == company_id)
        return list(self.s.scalars(stmt.order_by(OutreachDraft.created_at.desc())))
