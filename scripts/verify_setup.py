"""Check that the local environment is ready and report each check honestly.

Usage:
    uv run python scripts/verify_setup.py
Exit code 0 when every required check passes.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable

from sqlalchemy import func, select, text

REQUIRED_PACKAGES = [
    "streamlit",
    "pandas",
    "sqlalchemy",
    "alembic",
    "pydantic",
    "pydantic_settings",
    "plotly",
    "httpx",
    "bs4",
    "dotenv",
]


def check_python() -> str:
    if sys.version_info < (3, 12):  # noqa: UP036 - runtime check for users' interpreters
        raise RuntimeError(f"Python 3.12+ required, found {sys.version.split()[0]}")
    return sys.version.split()[0]


def check_packages() -> str:
    versions = []
    for name in REQUIRED_PACKAGES:
        module = importlib.import_module(name)
        versions.append(f"{name} {getattr(module, '__version__', '?')}")
    return ", ".join(versions)


def check_settings() -> str:
    from cyberlead360.config.settings import get_settings

    s = get_settings()
    return f"env={s.app_env}, llm_provider={s.llm_provider}, llm_enabled={s.llm_enabled}"


def check_database() -> str:
    from cyberlead360.config.settings import get_settings
    from cyberlead360.database.models import Company
    from cyberlead360.database.session import Database, schema_is_initialized

    db = Database(get_settings())
    with db.engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    if not schema_is_initialized(db.engine):
        raise RuntimeError("schema missing — run scripts/initialize_database.py")
    with db.session() as s:
        n = s.scalar(select(func.count(Company.id))) or 0
    return f"connected, schema present, {n} companies"


def check_scoring() -> str:
    from cyberlead360.domain.scoring_rules import (
        CompanyProfile,
        RuleSet,
        ScoringConfig,
        calculate_lead_score,
    )

    result = calculate_lead_score(
        CompanyProfile(industry="healthcare", employee_count=300, country="FR"),
        [],
        RuleSet(version=1, config=ScoringConfig()),
    )
    return f"engine OK (sample score {result.total_score}/100)"


def check_template_ai() -> str:
    from cyberlead360.domain.enums import Language, MessageType, ServiceLine, Tone
    from cyberlead360.services.ai_service import CompanyContext
    from cyberlead360.services.outreach_templates import render_template

    ctx = CompanyContext(1, "Example Co", None, "FR", "51-200", None)
    draft = render_template(
        ctx,
        MessageType.COLD_EMAIL,
        Tone.PROFESSIONAL,
        Language.EN,
        ServiceLine.SECURITY_AWARENESS,
        "A. Sender",
        "Sec Firm",
    )
    return f"template generation OK ({len(draft.body)} chars)"


CHECKS: list[tuple[str, Callable[[], str], bool]] = [
    ("Python version", check_python, True),
    ("Dependencies", check_packages, True),
    ("Configuration", check_settings, True),
    ("Database", check_database, True),
    ("Scoring engine", check_scoring, True),
    ("Template outreach (no API key)", check_template_ai, True),
]


def main() -> int:
    failures = 0
    for label, fn, required in CHECKS:
        try:
            print(f"[ OK ] {label}: {fn()}")
        except Exception as exc:
            failures += required
            print(f"[FAIL] {label}: {exc}")
    print("All checks passed." if not failures else f"{failures} check(s) failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
