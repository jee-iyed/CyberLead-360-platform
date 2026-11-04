"""Seed the database with deterministic, ENTIRELY FICTIONAL demo data.

Usage (PowerShell or bash):
    uv run python scripts/seed_demo.py            # refuses if data exists
    uv run python scripts/seed_demo.py --reset    # wipe all rows, then seed
"""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime

from sqlalchemy import func, select

from cyberlead360.database.models import Company
from cyberlead360.database.session import Database
from cyberlead360.demo_seed import seed, wipe


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--reset", action="store_true", help="delete ALL existing rows first")
    parser.add_argument(
        "--anchor-date",
        type=date.fromisoformat,
        default=datetime.now(UTC).date(),
        help="reference day for relative dates (YYYY-MM-DD)",
    )
    args = parser.parse_args()

    db = Database()
    db.ensure_schema()
    with db.session() as s:
        existing = s.scalar(select(func.count(Company.id))) or 0
    if existing and not args.reset:
        print(f"Database already contains {existing} companies. Use --reset to replace them.")
        return 1
    if args.reset:
        wipe(db)
    stats = seed(db, args.anchor_date)
    print("Demo data created (fictional):", ", ".join(f"{k}={v}" for k, v in stats.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
