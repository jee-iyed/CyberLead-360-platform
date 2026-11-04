"""Timezone-aware date helpers. The application stores and computes in UTC."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime | None) -> datetime | None:
    """Attach UTC to naive datetimes (assumed UTC) and convert aware ones to UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def start_of_day_utc(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


def days_between(earlier: datetime, later: datetime) -> int:
    return (ensure_utc(later) - ensure_utc(earlier)).days  # type: ignore[operator]


def age_in_days(value: datetime | None, now: datetime | None = None) -> int | None:
    if value is None:
        return None
    return days_between(value, now or utcnow())


def freshness_label(
    observed: datetime | None, threshold_days: int, now: datetime | None = None
) -> str:
    """Return ``fresh`` / ``ageing`` / ``stale`` / ``unknown`` for a fact's date."""
    age = age_in_days(observed, now)
    if age is None:
        return "unknown"
    if age <= threshold_days // 2:
        return "fresh"
    if age <= threshold_days:
        return "ageing"
    return "stale"


def month_start(value: datetime) -> date:
    return date(value.year, value.month, 1)


def add_days(value: datetime, days: int) -> datetime:
    return value + timedelta(days=days)
