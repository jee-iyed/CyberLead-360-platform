"""Create or upgrade the database schema (Alembic ``upgrade head``) and default rules.

Usage:
    uv run python scripts/initialize_database.py
"""

from __future__ import annotations

from cyberlead360.config.settings import get_settings
from cyberlead360.database.session import Database, run_migrations
from cyberlead360.services.scoring_service import ScoringService


def main() -> int:
    settings = get_settings()
    run_migrations(settings.database_url)
    db = Database(settings)
    with db.session() as s:
        rule = ScoringService(s, settings.operator_name).ensure_default_rules()
        version = rule.version
    backend = "SQLite" if settings.is_sqlite else settings.database_url.split("://")[0]
    print(f"Database ready ({backend}). Active scoring rules: v{version}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
