"""Assemble the bot: Bot, Dispatcher, member middleware, DB injection.

Phase 4 (app/main.py) calls create_bot() + create_dispatcher(db) in the FastAPI
lifespan and feeds Telegram updates via dp.feed_update(bot, update).
"""

from __future__ import annotations

from typing import Optional

import aiosqlite
from aiogram import BaseMiddleware, Bot, Dispatcher

from .. import queries
from ..config import settings
from . import bill_flow, checks, fine_flow, onboarding


class MemberMiddleware(BaseMiddleware):
    """Resolve the Telegram user to a flat member once per update and inject it
    as `member` (None if unknown). Handlers declare `member` to receive it."""

    async def __call__(self, handler, event, data):
        db: Optional[aiosqlite.Connection] = data.get("db")
        user = data.get("event_from_user")
        if db is not None and user is not None:
            data["member"] = await queries.get_member_by_telegram(db, user.id)
        else:
            data["member"] = None
        return await handler(event, data)


def create_bot() -> Optional[Bot]:
    """The Bot, or None when no token is configured (BR-060: web still boots)."""
    if not settings.bot_enabled:
        return None
    return Bot(token=settings.bot_token)


def create_dispatcher(db: aiosqlite.Connection) -> Dispatcher:
    """A Dispatcher wired with the shared DB connection, the member middleware,
    and every router. Independent of the Bot, so it's easy to test offline."""
    dp = Dispatcher()
    dp["db"] = db  # injected into every handler that declares `db`

    member_mw = MemberMiddleware()
    dp.message.middleware(member_mw)
    dp.callback_query.middleware(member_mw)

    dp.include_router(onboarding.router)
    dp.include_router(checks.router)
    dp.include_router(fine_flow.router)
    dp.include_router(bill_flow.router)
    return dp
