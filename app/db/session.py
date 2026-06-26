"""Async engine, session factory, and unit-of-work helpers.

Session lifecycle is explicit and consistent:
  * `get_session` — FastAPI dependency: one session per request, committed on
    success and rolled back on error (a clean transactional unit of work).
  * `session_scope` — the same contract as a context manager, for the background
    sweep, the admin CLI, and tests.

Repositories never commit; the owner of the session (request / scope) does. That
removes the old "every query commits" hidden side effect and makes multi-step
writes atomic.

NullPool: SQLite is a single file and connections are cheap; not pooling avoids
cross-event-loop binding issues (e.g. TestClient + a module-level engine) and
suits the single-writer model. PRAGMAs are (re)applied on every connect.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.base import Base
from app.db import models  # noqa: F401  (registers tables on Base.metadata)

engine = create_async_engine(settings.async_database_url, poolclass=NullPool)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: a request-scoped session, committed on success."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Unit of work for non-request callers (sweep, CLI, tests)."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_all() -> None:
    """Provision a fresh DB (dev / tests / first boot). Idempotent — only creates
    missing tables. Alembic is the source of truth for evolving an existing DB."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose() -> None:
    await engine.dispose()
