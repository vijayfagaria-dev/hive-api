"""Small shared helpers for handlers."""

from __future__ import annotations

from typing import Optional

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InaccessibleMessage, InlineKeyboardMarkup, Message

UNREGISTERED = "You're not set up in the flat yet — send /start to join."


async def require_member(event, member) -> bool:
    """True if the caller is a known, active member. Otherwise nudges them to
    /start and returns False so the handler can bail."""
    if member is not None and member["is_active"]:
        return True
    if isinstance(event, CallbackQuery):
        await event.answer(UNREGISTERED, show_alert=True)
    else:
        await event.answer(UNREGISTERED)
    return False


async def safe_edit(
    message, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None
) -> None:
    """edit_text that no-ops instead of crashing on the cases a callback edit
    can't handle: a missing message (callback older than ~48h → message is None),
    an InaccessibleMessage, or 'message is not modified' / 'can't be edited'.

    This is the single home for all callback-driven edits — route every
    `callback.message` edit through here."""
    if message is None or isinstance(message, InaccessibleMessage):
        return
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest:
        pass
