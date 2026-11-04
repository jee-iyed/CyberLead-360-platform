"""Two-phase CSV import of companies: ``preview`` (validate everything) then ``commit``.

* No row is ever discarded silently: every invalid row is reported with its line
  number and error messages, and can be downloaded for correction.
* Duplicates (inside the file or against the database) are classified and the
  user chooses the policy. Existing records are never overwritten by an import.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Literal

import pandas as pd
from pydantic import ValidationError
from sqlalchemy.orm import Session

from cyberlead360.database.models import CompanySource
from cyberlead360.domain.enums import SourceType
from cyberlead360.domain.exceptions import DuplicateCompanyError, ImportValidationError
from cyberlead360.domain.schemas import CompanyCreate
from cyberlead360.services.company_service import CompanyService
from cyberlead360.utils.normalization import normalize_company_name, normalize_domain

REQUIRED_COLUMNS = {"company_name"}
OPTIONAL_COLUMNS = {
    "website",
    "industry",
    "subindustry",
    "country",
    "city",
    "employee_count",
    "description",
    "cybersecurity_interest",
    "owner",
}
ALLOWED_COLUMNS = REQUIRED_COLUMNS | OPTIONAL_COLUMNS
COLUMN_ALIASES = {
    "name": "company_name",
    "company": "company_name",
    "domain": "website",
    "url": "website",
    "sector": "industry",
    "employees": "employee_count",
    "headcount": "employee_count",
}
DuplicatePolicy = Literal["skip", "create_flagged"]


@dataclass
class RowIssue:
    row_number: int  # 1-based line number in the file, header = line 1
    company_name: str
    errors: list[str]


@dataclass
class PreviewRow:
    row_number: int
    data: CompanyCreate
    duplicate_status: Literal[
        "new", "possible_duplicate", "definite_duplicate", "in_file_duplicate"
    ]
    duplicate_reason: str = ""


@dataclass
class ImportPreview:
    filename: str
    total_rows: int
    rows: list[PreviewRow] = field(default_factory=list)
    invalid: list[RowIssue] = field(default_factory=list)
    ignored_columns: list[str] = field(default_factory=list)

    def count(self, status: str) -> int:
        return sum(1 for r in self.rows if r.duplicate_status == status)

    def invalid_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "line": i.row_number,
                    "company_name": i.company_name,
                    "errors": "; ".join(i.errors),
                }
                for i in self.invalid
            ]
        )

    def preview_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "line": r.row_number,
                    "company_name": r.data.company_name,
                    "website": r.data.website,
                    "industry": r.data.industry.value if r.data.industry else None,
                    "country": r.data.country,
                    "employees": r.data.employee_count,
                    "status": r.duplicate_status,
                    "reason": r.duplicate_reason,
                }
                for r in self.rows
            ]
        )


@dataclass
class ImportResult:
    created: int = 0
    skipped_duplicates: int = 0
    invalid: int = 0
    created_ids: list[int] = field(default_factory=list)


def _format_errors(exc: ValidationError) -> list[str]:
    messages = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "row"
        msg = err["msg"].removeprefix("Value error, ")
        messages.append(f"{loc}: {msg}")
    return messages


class ImportService:
    def __init__(self, session: Session, actor: str, max_bytes: int, max_rows: int) -> None:
        self.s = session
        self.actor = actor
        self.max_bytes = max_bytes
        self.max_rows = max_rows
        self.companies = CompanyService(session, actor)

    def read_csv(self, content: bytes) -> pd.DataFrame:
        if len(content) > self.max_bytes:
            raise ImportValidationError(
                f"File is too large ({len(content) / 1_048_576:.1f} MB). "
                f"Limit: {self.max_bytes / 1_048_576:.1f} MB."
            )
        if not content.strip():
            raise ImportValidationError("The file is empty.")
        text = None
        for encoding in ("utf-8-sig", "cp1252"):
            try:
                text = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise ImportValidationError("Unsupported encoding. Save the file as UTF-8 CSV.")
        try:
            delimiter = csv.Sniffer().sniff(text[:4096], delimiters=",;	").delimiter
        except csv.Error:
            delimiter = ","  # single-column files cannot be sniffed
        try:
            df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False, sep=delimiter)
        except (pd.errors.ParserError, ValueError) as exc:
            raise ImportValidationError(f"The CSV could not be parsed: {exc}") from exc
        df.columns = [COLUMN_ALIASES.get(c.strip().lower(), c.strip().lower()) for c in df.columns]
        missing = REQUIRED_COLUMNS - set(df.columns)
        if missing:
            raise ImportValidationError(f"Missing required column(s): {', '.join(sorted(missing))}")
        if len(df) > self.max_rows:
            raise ImportValidationError(f"Too many rows ({len(df)}). Limit: {self.max_rows}.")
        return df

    def preview(self, content: bytes, filename: str) -> ImportPreview:
        df = self.read_csv(content)
        ignored = sorted(set(df.columns) - ALLOWED_COLUMNS)
        preview = ImportPreview(filename=filename, total_rows=len(df), ignored_columns=ignored)
        seen_domains: dict[str, int] = {}
        seen_names: dict[str, int] = {}
        for idx, raw in enumerate(df.to_dict(orient="records")):
            line = idx + 2  # header is line 1
            values = {k: (v if v != "" else None) for k, v in raw.items() if k in ALLOWED_COLUMNS}
            try:
                data = CompanyCreate(**values)
            except ValidationError as exc:
                preview.invalid.append(
                    RowIssue(line, str(raw.get("company_name") or ""), _format_errors(exc))
                )
                continue
            except ValueError as exc:
                preview.invalid.append(
                    RowIssue(line, str(raw.get("company_name") or ""), [str(exc)])
                )
                continue

            domain = normalize_domain(data.website)
            norm = normalize_company_name(data.company_name)
            if domain and domain in seen_domains:
                preview.rows.append(
                    PreviewRow(
                        line,
                        data,
                        "in_file_duplicate",
                        f"Same domain as line {seen_domains[domain]}",
                    )
                )
                continue
            if norm in seen_names:
                preview.rows.append(
                    PreviewRow(
                        line, data, "in_file_duplicate", f"Same name as line {seen_names[norm]}"
                    )
                )
                continue
            if domain:
                seen_domains[domain] = line
            seen_names[norm] = line

            dups = self.companies.find_duplicates(data.company_name, data.website, data.country)
            definite = [d for d in dups if d.certainty == "definite"]
            if definite:
                d = definite[0]
                preview.rows.append(
                    PreviewRow(
                        line,
                        data,
                        "definite_duplicate",
                        f"{d.reason}: {d.company_name} (#{d.company_id})",
                    )
                )
            elif dups:
                d = dups[0]
                preview.rows.append(
                    PreviewRow(
                        line,
                        data,
                        "possible_duplicate",
                        f"{d.reason}: {d.company_name} (#{d.company_id})",
                    )
                )
            else:
                preview.rows.append(PreviewRow(line, data, "new"))
        return preview

    def commit(self, preview: ImportPreview, policy: DuplicatePolicy = "skip") -> ImportResult:
        """Create companies from a preview inside the caller's transaction."""
        result = ImportResult(invalid=len(preview.invalid))
        for row in preview.rows:
            if row.duplicate_status in ("definite_duplicate", "in_file_duplicate"):
                result.skipped_duplicates += 1
                continue
            if row.duplicate_status == "possible_duplicate" and policy == "skip":
                result.skipped_duplicates += 1
                continue
            try:
                company = self.companies.create(
                    row.data,
                    confirm_possible_duplicate=(policy == "create_flagged"),
                    source_label=f"csv:{preview.filename[:80]}",
                )
            except DuplicateCompanyError:
                result.skipped_duplicates += 1  # created meanwhile by an earlier row
                continue
            self.s.add(
                CompanySource(
                    company_id=company.id,
                    source_type=SourceType.CSV_IMPORT.value,
                    title=f"CSV import: {preview.filename[:200]} (line {row.row_number})",
                    collected_by=self.actor,
                )
            )
            result.created += 1
            result.created_ids.append(company.id)
        return result
