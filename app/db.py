"""SQLite access: one shared connection, schema bootstrap, time helpers.

One app, one SQLite file (see CLAUDE.md). For a 4–6 person flat a single
serialized connection is plenty — no pool needed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite

from .config import settings

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


# --- Time helpers (UTC, ISO-8601) -----------------------------------------
# Stored as TEXT so the dashboard can render them and SQLite can sort them.

def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso() -> str:
    return iso(now())


def deadline_iso(base: datetime, hours: int) -> str:
    """ISO deadline = base + hours. Pass the SAME base used for the row's `ts`
    so confirm_deadline is exactly ts + COOLING_HOURS (BR-031), not ts+hours-ε."""
    return iso(base + timedelta(hours=hours))


# --- Connection lifecycle --------------------------------------------------

async def connect() -> aiosqlite.Connection:
    """Open the shared connection, apply schema, seed if empty."""
    db = await aiosqlite.connect(settings.database_path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode = WAL;")
    await db.execute("PRAGMA foreign_keys = ON;")
    await _apply_schema(db)
    await _migrate(db)
    await _seed_if_empty(db)
    return db


async def _apply_schema(db: aiosqlite.Connection) -> None:
    await db.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    await db.commit()


async def _migrate(db: aiosqlite.Connection) -> None:
    """Evolve existing DBs without a migration framework (no "delete the db").

    Idempotent: adds any missing columns, then (re)creates the case-insensitive
    username index. Fresh DBs already have the columns from schema.sql, so the
    ALTERs are skipped and only the index is ensured.
    """
    async with db.execute("PRAGMA table_info(members)") as cur:
        cols = {row["name"] for row in await cur.fetchall()}
    for col in ("username", "password_hash"):
        if col not in cols:
            await db.execute(f"ALTER TABLE members ADD COLUMN {col} TEXT")
    await db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_members_username "
        "ON members(lower(username))"
    )
    await db.commit()


async def _seed_if_empty(db: aiosqlite.Connection) -> None:
    """First boot only: load the starter rule set so the bot has buttons."""
    async with db.execute("SELECT COUNT(*) FROM rules") as cur:
        (count,) = await cur.fetchone()
    if count == 0:
        from .seed import seed_rules

        await seed_rules(db)
