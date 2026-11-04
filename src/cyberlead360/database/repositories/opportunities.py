"""Opportunity data access."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from cyberlead360.database.models import Company, Opportunity


class OpportunityRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def get(self, opportunity_id: int) -> Opportunity | None:
        return self.s.get(Opportunity, opportunity_id)

    def add(self, opp: Opportunity) -> Opportunity:
        self.s.add(opp)
        self.s.flush()
        return opp

    def list(
        self, stages: list[str] | None = None, company_id: int | None = None
    ) -> list[tuple[Opportunity, str]]:
        stmt = select(Opportunity, Company.company_name).join(Company)
        if stages:
            stmt = stmt.where(Opportunity.stage.in_(stages))
        if company_id:
            stmt = stmt.where(Opportunity.company_id == company_id)
        stmt = stmt.order_by(Opportunity.updated_at.desc())
        return [(r[0], r[1]) for r in self.s.execute(stmt)]

    def open_for_company(self, company_id: int) -> list[Opportunity]:
        return list(
            self.s.scalars(
                select(Opportunity).where(
                    Opportunity.company_id == company_id,
                    Opportunity.stage.in_(["open", "proposal_sent"]),
                )
            )
        )
