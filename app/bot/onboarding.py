"""Onboarding: /start, /addtenant, and claiming a spot.

v1 onboarding model (a plan refinement — see api-surface.md):
  * The FIRST ever /start (empty DB) creates the founding tenant and links them.
  * After that, existing tenants add flatmates by name with `/addtenant <name>`.
  * A new person then /starts and taps "That's me — <name>" to link their account.

This keeps BR-010 intact: nobody silently becomes a tenant — they either bootstrap
an empty flat or claim a record a tenant deliberately created.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

from .. import queries
from . import callbacks as cb
from . import keyboards as kb
from .common import require_member, safe_edit

router = Router(name="onboarding")

_GREETING = (
    "👋 Hey {name}! I'm the flat bot. Try:\n"
    "  /fine — report a fine\n"
    "  /pot — what's in the jar\n"
    "  /dues — what you owe\n"
    "  /bill — log a bill\n"
    "  /rules — the house rules"
)


@router.message(CommandStart())
async def cmd_start(message: Message, db, member) -> None:
    if member is not None and member["is_active"]:
        await message.answer(_GREETING.format(name=member["name"]))
        return

    if not await queries.has_any_member(db):
        # Founder bootstrap — someone has to be first. Keys off "ever had a member"
        # so deactivating everyone can't silently mint a new founder.
        name = message.from_user.full_name or message.from_user.first_name or "Tenant"
        await queries.add_member(db, name, telegram_id=message.from_user.id)
        await message.answer(
            f"🏠 Welcome to Hive, {name}! You're the founding tenant.\n\n"
            + _GREETING.format(name=name)
        )
        return

    unlinked = await queries.list_unlinked_tenants(db)
    if unlinked:
        await message.answer("👋 Welcome! Which one are you?", reply_markup=kb.claim_kb(unlinked))
    else:
        await message.answer(
            "👋 Welcome! You're not on the flat roster yet. Ask a flatmate to run "
            "/addtenant <your name>, then send /start again."
        )


@router.message(Command("addtenant"))
async def cmd_addtenant(message: Message, command: CommandObject, db, member) -> None:
    if not await require_member(message, member):
        return
    name = (command.args or "").strip()
    if not name:
        await message.answer("Usage: /addtenant <name> — e.g. /addtenant Priya")
        return
    existing = await queries.get_active_member_by_name(db, name)
    if existing is not None:
        state = "already linked" if existing["telegram_id"] else "awaiting their /start"
        await message.answer(f"{existing['name']} is already on the roster ({state}).")
        return
    await queries.add_member(db, name)  # no telegram_id yet — they claim via /start
    await message.answer(
        f"✅ Added {name} as a tenant. They can now send /start and tap "
        f"“That's me — {name}”."
    )


@router.callback_query(cb.Claim.filter())
async def cb_claim(callback: CallbackQuery, callback_data: cb.Claim, db) -> None:
    tg_id = callback.from_user.id
    existing = await queries.get_member_by_telegram(db, tg_id)
    if existing is not None:
        await callback.answer(f"You're already linked as {existing['name']}.", show_alert=True)
        return
    target = await queries.get_member(db, callback_data.member_id)
    if target is None or target["telegram_id"] is not None or not target["is_active"]:
        await callback.answer("That spot's already taken — send /start again.", show_alert=True)
        return
    await queries.link_telegram(db, target["id"], tg_id)
    await callback.answer()
    await safe_edit(
        callback.message,
        f"✅ You're in, {target['name']}! Send /fine, /pot or /dues to get going.",
    )
