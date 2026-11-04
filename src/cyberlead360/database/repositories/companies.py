"""Company data access. All queries are parameterized through the ORM."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from cyberlead360.database.models import Company, ScoringResult


@dataclass
class CompanyFilters:
    search: str | None = None
    industries: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    stages: list[str] = field(default_factory=list)
    min_employees: int | None = None
    max_employees: int | None = None
    min_score: int | None = None
    max_score: int | None = None
    include_archived: bool = False


class CompanyRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def get(self, company_id: int) -> Company | None:
        return self.s.get(Company, company_id)

    def add(self, company: Company) -> Company:
        self.s.add(company)
        self.s.flush()
        return company

    def by_domain(self, domain: str) -> Company | None:
        return self.s.scalar(select(Company).where(Company.normalized_domain == domain))

    def by_normalized_name(self, normalized_name: str) -> list[Company]:
        return list(
            self.s.scalars(select(Company).where(Company.normalized_name == normalized_name))
        )

    def all_active_name_index(self) -> list[tuple[int, str, str | None, str | None]]:
        """(id, normalized_name, country, domain) for fuzzy duplicate checks."""
        rows = self.s.execute(
            select(
                Company.id, Company.normalized_name, Company.country, Company.normalized_domain
            ).where(Company.merged_into_id.is_(None))
        )
        return [tuple(r) for r in rows]  # type: ignore[misc]

    def _filtered(self, f: CompanyFilters) -> Select[tuple[Company, int | None, str | None]]:
        score = (
            select(
                ScoringResult.company_id,
                ScoringResult.total_score,
                ScoringResult.priority,
            )
            .where(ScoringResult.is_current.is_(True))
            .subquery()
        )
        stmt = select(Company, score.c.total_score, score.c.priority).outerjoin(
            score, score.c.company_id == Company.id
        )
        if not f.include_archived:
            stmt = stmt.where(Company.archived_at.is_(None))
        if f.search:
            # Escape LIKE wildcards in user input; value is still bound as a parameter.
            term = f.search.strip().lower().replace("\\", "\\\\")
            term = term.replace("%", "\\%").replace("_", "\\_")
            like = f"%{term}%"
            stmt = stmt.where(
                or_(
                    func.lower(Company.company_name).like(like, escape="\\"),
                    Company.normalized_domain.like(like, escape="\\"),
                    func.lower(Company.city).like(like, escape="\\"),
                )
            )
        if f.industries:
            stmt = stmt.where(Company.industry.in_(f.industries))
        if f.countries:
            stmt = stmt.where(Company.country.in_(f.countries))
        if f.stages:
            stmt = stmt.where(Company.prospect_stage.in_(f.stages))
        if f.min_employees is not None:
            stmt = stmt.where(Company.employee_count >= f.min_employees)
        if f.max_employees is not None:
            stmt = stmt.where(Company.employee_count <= f.max_employees)
        if f.min_score is not None:
            stmt = stmt.where(func.coalesce(score.c.total_score, 0) >= f.min_score)
        if f.max_score is not None:
            stmt = stmt.where(func.coalesce(score.c.total_score, 0) <= f.max_score)
        return stmt

    def search(
        self, f: CompanyFilters, limit: int = 1000
    ) -> list[tuple[Company, int | None, str | None]]:
        stmt = self._filtered(f).limit(limit)
        rows = self.s.execute(stmt).all()
        # Sort by priority (score desc, then name) in Python for portability.
        return sorted(
            [(r[0], r[1], r[2]) for r in rows],
            key=lambda r: (-(r[1] if r[1] is not None else -1), r[0].company_name.lower()),
        )

    def active_ids(self) -> list[int]:
        return list(self.s.scalars(select(Company.id).where(Company.archived_at.is_(None))))

    def count_active(self) -> int:
        return (
            self.s.scalar(select(func.count(Company.id)).where(Company.archived_at.is_(None))) or 0
        )

    def distinct_values(self, column: str) -> list[str]:
        col = getattr(Company, column)
        return [
            v
            for v in self.s.scalars(select(col).distinct().where(col.is_not(None)).order_by(col))
            if v
        ]

    def options(self, include_archived: bool = False) -> list[tuple[int, str]]:
        stmt = select(Company.id, Company.company_name).order_by(Company.company_name)
        if not include_archived:
            stmt = stmt.where(Company.archived_at.is_(None))
        return [(r[0], r[1]) for r in self.s.execute(stmt)]
