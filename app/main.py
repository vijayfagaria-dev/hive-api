"""Hive — FastAPI app: Telegram webhook + JSON API (/api/*) + health.

The web UI is the **Next.js frontend** in `frontend/` (it consumes `/api`). This
process serves the JSON API, the Telegram bot webhook, and runs the pending-fine
sweep. Boots fine with no bot token — the API + sweep still run.

    uvicorn app.main:app --reload      # API on :8000
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from aiogram.types import Update
from fastapi import FastAPI, HTTPException, Request, Response
from starlette.middleware.sessions import SessionMiddleware

from . import api, fines
from .bot import create_bot, create_dispatcher
from .config import settings
from .db import connect

logger = logging.getLogger("hive")


async def _sweep_loop(db) -> None:
    """Promote overdue, undisputed pending fines on an interval (BR-032). Runs
    once immediately, then every SWEEP_INTERVAL_SECONDS. One bad pass never kills
    the loop."""
    while True:
        try:
            promoted = await fines.sweep_due(db)
            if promoted:
                logger.info("Sweep confirmed %d fine(s): %s", len(promoted), promoted)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Fine sweep failed")
        await asyncio.sleep(settings.sweep_interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = await connect()
    app.state.db = db
    app.state.bot = None
    app.state.dp = None
    bot = None
    sweep = None
    try:
        # Logins are only as safe as the cookie-signing key. Warn unconditionally —
        # a default/empty key makes sessions forgeable.
        if settings.secret_key in ("", "hive-dev-secret"):
            logger.warning(
                "SECRET_KEY (session signing) is unset/default - set a random "
                "SECRET_KEY (or WEBHOOK_SECRET) before exposing logins; sessions "
                "are forgeable otherwise."
            )
        sweep = asyncio.create_task(_sweep_loop(db))
        bot = create_bot()
        app.state.bot = bot
        if bot is not None:
            dp = create_dispatcher(db)
            app.state.dp = dp
            if settings.webhook_url:
                if settings.webhook_secret == "hive-dev-secret":
                    logger.warning(
                        "WEBHOOK_SECRET is the built-in default - set a random "
                        "WEBHOOK_SECRET before exposing the bot publicly (BR-061)."
                    )
                try:
                    await bot.set_webhook(
                        settings.webhook_url,
                        secret_token=settings.webhook_secret,
                        allowed_updates=dp.resolve_used_update_types(),
                        drop_pending_updates=True,
                    )
                    logger.info("Telegram webhook registered at %s", settings.webhook_url)
                except Exception:
                    # Non-fatal: the API/health still serve. Fix + restart.
                    logger.exception("set_webhook failed - continuing API-only.")
            else:
                logger.warning("Bot token set but WEBHOOK_BASE_URL is empty - no webhook registered.")
        else:
            logger.info("No bot token - running API-only (no Telegram).")
        yield
    finally:
        # Always release resources, even if startup raised partway through.
        if sweep is not None:
            sweep.cancel()
            try:
                await sweep
            except asyncio.CancelledError:
                pass
        if bot is not None:
            await bot.session.close()
        await db.close()


app = FastAPI(title="Hive — Flat Bot", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="hive_session",
    max_age=60 * 60 * 24 * 30,
    same_site="lax",
    https_only=settings.cookie_secure,
)

# The JSON API consumed by the Next.js frontend.
app.include_router(api.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post(settings.webhook_path)
async def telegram_webhook(request: Request) -> Response:
    bot = request.app.state.bot
    dp = request.app.state.dp
    if bot is None or dp is None:
        raise HTTPException(status_code=404)  # bot disabled (BR-060)
    # Two layers (BR-061): the unguessable path AND Telegram's secret-token header.
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != settings.webhook_secret:
        raise HTTPException(status_code=403)
    # Always ACK 200 — bot replies go out via the API, not this response body. A
    # handler raise or a malformed body must NOT become a 5xx, or Telegram retries
    # the same update (re-running side effects, e.g. a duplicate fine).
    try:
        update = Update.model_validate(await request.json())
        await dp.feed_update(bot, update)
    except Exception:
        logger.exception("Webhook update handling failed")
    return Response(status_code=200)
