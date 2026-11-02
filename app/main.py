"""Hive — FastAPI app factory: JSON API (/api/*) + health + the complaint sweep.

Web-first (the Telegram bot was retired). Wiring only — every concern lives in
its layer: routes (api/), business logic (services/), data access (repositories/),
ORM (db/), cross-cutting (core/).

    uvicorn app.main:app --reload      # API on :8000
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.errors import install_exception_handlers
from app.core.logging import configure_logging
from app.db import session as db
from app.db.seed import seed_if_empty
from app.infra import mailer
from app.services import billing, complaints, notifications, otp, proposals, recurring

logger = logging.getLogger("hive")


async def _sweep_loop() -> None:
    """On an interval: auto-confirm overdue complaints + finalize closed votes.
    Runs once immediately, then every SWEEP_INTERVAL_SECONDS. One bad pass never
    kills the loop. Each pass is its own transactional session scope."""
    while True:
        try:
            async with db.session_scope() as session:
                promoted = await complaints.sweep_due(session)
                finalized = await complaints.sweep_votes(session)
                overdue = await complaints.sweep_overdue(session)
                closed = await proposals.sweep_due(session)
                bills_confirmed = await billing.sweep_due(session)
                recurring_made = await recurring.sweep_due(session)
                await otp.purge(session)
            if promoted:
                logger.info("Sweep confirmed %d complaint(s): %s", len(promoted), promoted)
            if finalized:
                logger.info("Sweep finalized %d complaint vote(s): %s", len(finalized), finalized)
            if overdue:
                logger.info("Sweep marked %d fine(s) overdue: %s", len(overdue), overdue)
            if closed:
                logger.info("Sweep closed %d proposal(s): %s", len(closed), closed)
            if bills_confirmed:
                logger.info("Sweep confirmed %d bill(s): %s", len(bills_confirmed), bills_confirmed)
            if recurring_made:
                logger.info("Sweep generated %d recurring expense(s): %s", len(recurring_made), recurring_made)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Complaint sweep failed")
        await asyncio.sleep(settings.sweep_interval_seconds)


async def _notify_dispatch_loop() -> None:
    """On a short interval: drain the notification outbox (push/email/WhatsApp) in its
    own sessions, so external sends never run inside a request's DB transaction. One bad
    pass never kills the loop."""
    while True:
        try:
            sent = await notifications.dispatch_outbox()
            if sent:
                logger.info("Dispatched %d queued notification(s)", sent)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Notification dispatch failed")
        await asyncio.sleep(settings.notify_dispatch_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    # Provision a fresh DB for dev/tests/first boot; Alembic owns prod migrations.
    await db.create_all()
    async with db.session_scope() as session:
        await seed_if_empty(session)
    if settings.secret_key in ("", "hive-dev-secret"):
        logger.warning(
            "SECRET_KEY (session signing) is unset/default - set a random SECRET_KEY "
            "before exposing logins; sessions are forgeable otherwise."
        )
    if not settings.email_enabled:
        logger.warning(
            "SMTP not configured - signup/reset codes are logged instead of emailed (dev only)."
        )
    if not settings.push_enabled:
        logger.info("Web Push disabled (no VAPID keys) - notifications go in-app + email/WhatsApp.")
    tasks = [asyncio.create_task(_sweep_loop()), asyncio.create_task(_notify_dispatch_loop())]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        await mailer.drain()
        await db.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="Hive — Flat API", lifespan=lifespan)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="hive_session",
        max_age=60 * 60 * 24 * settings.session_max_age_days,
        same_site="lax",
        https_only=settings.cookie_secure,
    )
    install_exception_handlers(app)
    app.include_router(api_router)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
