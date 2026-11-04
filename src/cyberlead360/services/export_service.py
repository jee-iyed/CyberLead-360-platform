"""Exports to CSV/JSON.

* Cell values are neutralized against spreadsheet formula injection.
* Personal-data exports exclude anonymized / objected contacts unless explicitly
  requested, and are audited.
* Files written to disk are confined to the configured export directory.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from cyberlead360.database.models import (
    Activity,
    Company,
    Contact,
    Opportunity,
    ScoringResult,
)
from cyberlead360.database.repositories.activities import AuditRepository
from cyberlead360.domain.enums import ContactStatus, ObjectionStatus
from cyberlead360.domain.exceptions import ValidationFailedError
from cyberlead360.utils.date_utils import utcnow
from cyberlead360.utils.validators import neutralize_csv_formula

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,60}$")


def to_safe_csv(df: pd.DataFrame) -> bytes:
    safe = df.copy()
    for col in safe.columns:
        if safe[col].dtype == object or pd.api.types.is_string_dtype(safe[col]):
            safe[col] = safe[col].map(neutralize_csv_formula)
    return safe.to_csv(index=False).encode("utf-8-sig")


def safe_export_path(export_dir: Path, name: str, extension: str = "csv") -> Path:
    """Build a path inside ``export_dir``; reject traversal or odd names."""
    if not _SAFE_NAME_RE.match(name):
        raise ValidationFailedError("Export names may only contain letters, digits, - and _.")
    base = export_dir.resolve()
    target = (base / f"{name}.{extension}").resolve()
    if base not in target.parents:
        raise ValidationFailedError("Export path escapes the export directory.")
    return target


class ExportService:
    def __init__(self, session: Session, actor: str) -> None:
        self.s = session
        self.actor = actor
        self.audit = AuditRepository(session)

    def companies(self, include_archived: bool = False) -> pd.DataFrame:
        stmt = (
            select(
                Company.id,
                Company.company_name,
                Company.website,
                Company.industry,
                Company.subindustry,
                Company.country,
                Company.city,
                Company.employee_count,
                Company.employee_range,
                Company.prospect_stage,
                Company.qualification_status,
                Company.owner,
                Company.last_activity_at,
                Company.created_at,
                Company.updated_at,
                Company.archived_at,
                ScoringResult.total_score,
                ScoringResult.priority,
                ScoringResult.rules_version,
            )
            .outerjoin(
                ScoringResult,
                (ScoringResult.company_id == Company.id) & ScoringResult.is_current.is_(True),
            )
            .where(Company.merged_into_id.is_(None))
        )
        if not include_archived:
            stmt = stmt.where(Company.archived_at.is_(None))
        rows = self.s.execute(stmt.order_by(Company.company_name)).all()
        return (
            pd.DataFrame([r._asdict() for r in rows])
            if rows
            else pd.DataFrame(columns=[c.key for c in stmt.selected_columns])
        )

    def contacts(self, include_restricted: bool = False) -> pd.DataFrame:
        """Contact export. Restricted (objected/anonymized/do-not-contact) rows are
        excluded unless ``include_restricted`` — that case should be rare and is audited."""
        stmt = select(
            Contact.id,
            Company.company_name,
            Contact.first_name,
            Contact.last_name,
            Contact.job_title,
            Contact.department,
            Contact.professional_email,
            Contact.business_phone,
            Contact.contact_status,
            Contact.objection_status,
            Contact.last_contacted_at,
            Contact.lawful_basis_notes,
        ).join(Company, Company.id == Contact.company_id)
        if not include_restricted:
            stmt = stmt.where(
                Contact.contact_status == ContactStatus.ACTIVE.value,
                Contact.objection_status == ObjectionStatus.NONE.value,
            )
        rows = self.s.execute(stmt.order_by(Company.company_name, Contact.last_name)).all()
        self.audit.record(
            "contact",
            None,
            "exported",
            self.actor,
            {"rows": len(rows), "include_restricted": include_restricted},
        )
        return (
            pd.DataFrame([r._asdict() for r in rows])
            if rows
            else pd.DataFrame(columns=[c.key for c in stmt.selected_columns])
        )

    def opportunities(self) -> pd.DataFrame:
        rows = self.s.execute(
            select(
                Opportunity.id,
                Company.company_name,
                Opportunity.name,
                Opportunity.service_line,
                Opportunity.stage,
                Opportunity.estimated_value,
                Opportunity.currency,
                Opportunity.probability,
                Opportunity.expected_close_date,
                Opportunity.next_action,
                Opportunity.won_lost_reason,
                Opportunity.created_at,
                Opportunity.closed_at,
            )
            .join(Company)
            .order_by(Opportunity.created_at)
        ).all()
        df = pd.DataFrame([r._asdict() for r in rows])
        if not df.empty:
            df["estimated_value"] = df["estimated_value"].astype(float)
        return df

    def activities(self) -> pd.DataFrame:
        rows = self.s.execute(
            select(
                Activity.id,
                Company.company_name,
                Activity.activity_type,
                Activity.direction,
                Activity.subject,
                Activity.occurred_at,
                Activity.follow_up_at,
                Activity.follow_up_done,
                Activity.created_by,
            )
            .join(Company, Company.id == Activity.company_id)
            .order_by(Activity.occurred_at)
        ).all()
        return pd.DataFrame([r._asdict() for r in rows])

    def write_to_disk(self, df: pd.DataFrame, export_dir: Path, name: str) -> Path:
        """Used by scripts. UI downloads are streamed from memory instead."""
        path = safe_export_path(export_dir, f"{name}_{utcnow():%Y%m%d_%H%M%S}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(to_safe_csv(df))
        return path
