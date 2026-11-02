"""Time helpers — UTC, ISO-8601 TEXT (e.g. '2026-06-22T11:30:00Z').

Timestamps are stored as TEXT so SQLite can sort them lexically and the frontend
can render them verbatim. One home for the clock so deadlines line up exactly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso() -> str:
    return iso(now())


def deadline_iso(base: datetime, hours: int) -> str:
    """ISO timestamp = base + hours (negative hours -> a past cutoff). Pass the
    SAME base used for a row's `ts` so a deadline is exactly ts + hours."""
    return iso(base + timedelta(hours=hours))


def shift_iso(base: datetime, seconds: int) -> str:
    """ISO timestamp = base + seconds — for the sub-hour windows (OTP expiry, lockouts)."""
    return iso(base + timedelta(seconds=seconds))


def parse_iso(value: str) -> datetime:
    """Inverse of `iso` (the stored 'YYYY-MM-DDTHH:MM:SSZ' TEXT form)."""
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def seconds_until(value: str, base: datetime) -> int:
    """Whole seconds from `base` until the ISO timestamp `value` (0 if already past)."""
    return max(0, int((parse_iso(value) - base).total_seconds()))


def add_months(month: str, n: int) -> str:
    """'YYYY-MM' shifted by n months (n may be negative)."""
    y, m = int(month[:4]), int(month[5:7])
    total = y * 12 + (m - 1) + n
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def latest_local_month() -> str:
    """The furthest-ahead calendar month anywhere right now (UTC+14). Used as a lenient
    'current month' bound so a user just past midnight on the 1st is never told their
    month hasn't started yet."""
    return (now() + timedelta(hours=14)).strftime("%Y-%m")
