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
