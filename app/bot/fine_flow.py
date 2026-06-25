"""The /fine flow — the core feature. Stateless: rule + accused ride in the
callback data, so there's no FSM to get confused in a group chat.

  /fine [text] ─► pick a rule ─► pick the accused ─► fine card (Dispute button)

Rule selection honors BR-020 (never dump all rules): favorites + browse + search.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from .. import fines as fines_service
from .. import queries
from ..config import settings
from . import callbacks as cb
from . import formatting as fmt
from . import keyboards as kb
from .common import require_member, safe_edit

router = Router(name="fine")


@router.message(Command("fine"))
async def cmd_fine(message: Message, command: CommandObject, db, member) -> None:
    if not await require_member(message, member):
        return
    term = (command.args or "").strip()
    if term:
        rules = await queries.search_rules(db, term)
        if not rules:
            await message.answer(
                f"No rules match “{term}”. Send /fine on its own to browse."
            )
            return
        await message.answer(
            f"Rules matching “{term}” — pick one:",
            reply_markup=kb.fine_rules_kb(rules, with_browse=False),
        )
        return
    favorites = await queries.list_favorite_rules(db)
    await message.answer("🚨 What happened? Pick a rule:", reply_markup=kb.fine_rules_kb(favorites))


@router.callback_query(F.data == cb.FINE_CATS)
async def cb_fine_cats(callback: CallbackQuery, db) -> None:
    categories = await queries.list_categories(db)
    await callback.answer()
    await safe_edit(
        callback.message, "Pick a category:", kb.fine_categories_kb(categories)
    )


@router.callback_query(cb.FineCat.filter())
async def cb_fine_cat(callback: CallbackQuery, callback_data: cb.FineCat, db) -> None:
    rules = await queries.list_rules_by_category(db, callback_data.category)
    await callback.answer()
    await safe_edit(
        callback.message,
        f"{callback_data.category} rules — pick one:",
        kb.fine_rules_kb(rules),
    )


@router.callback_query(cb.FineRule.filter())
async def cb_fine_rule(callback: CallbackQuery, callback_data: cb.FineRule, db, member) -> None:
    if not await require_member(callback, member):
        return
    rule = await queries.get_rule(db, callback_data.rule_id)
    if rule is None:
        await callback.answer("That rule's gone.", show_alert=True)
        return
    # Accused picker: active members — tenants AND guests are finable (BR-R03) —
    # except the reporter (BR-034, no self-fine).
    accusable = [m for m in await queries.list_active_members(db) if m["id"] != member["id"]]
    if not accusable:
        await callback.answer("There's no one else to fine!", show_alert=True)
        return
    await callback.answer()
    await safe_edit(
        callback.message,
        f"“{rule['text']}” · {fmt.rupees(rule['fine_amount'])} — who did it?",
        kb.fine_who_kb(rule["id"], accusable),
    )


@router.callback_query(cb.FineWho.filter())
async def cb_fine_who(callback: CallbackQuery, callback_data: cb.FineWho, db, member) -> None:
    if not await require_member(callback, member):
        return
    try:
        fine_id = await fines_service.create_fine(
            db,
            accused_id=callback_data.member_id,
            added_by=member["id"],
            rule_id=callback_data.rule_id,
        )
    except fines_service.FineError as e:
        await callback.answer(str(e), show_alert=True)
        return

    fine = await queries.get_fine(db, fine_id)
    rule = await queries.get_rule(db, callback_data.rule_id)
    accused = await queries.get_member(db, callback_data.member_id)
    await callback.answer("Fine filed.")
    await safe_edit(
        callback.message,
        fmt.fine_card_text(
            accused=accused["name"],
            accuser=member["name"],
            rule_text=rule["text"] if rule else None,
            amount=fine["amount"],
            cooling_hours=settings.cooling_hours,
        ),
        kb.fine_card_kb(fine_id),
    )


@router.callback_query(cb.FineDispute.filter())
async def cb_fine_dispute(
    callback: CallbackQuery, callback_data: cb.FineDispute, db, member
) -> None:
    # Anyone in the flat can dispute (BR-033) — but they must be a member.
    if not await require_member(callback, member):
        return
    fine = await queries.get_fine(db, callback_data.fine_id)
    if fine is None:
        await callback.answer("That fine's gone.", show_alert=True)
        return
    moved = await fines_service.dispute(
        db, callback_data.fine_id, reason=f"disputed by {member['name']}"
    )
    if not moved:
        # `fine` was fetched while still the current row, so its status tells us why.
        already = "Already disputed." if fine["status"] == "disputed" else "Too late — it's already confirmed."
        await callback.answer(already, show_alert=True)
        return
    accused = await queries.get_member(db, fine["member_id"])
    await callback.answer("Disputed.")
    await safe_edit(
        callback.message,
        fmt.disputed_card_text(accused=accused["name"], amount=fine["amount"], by=member["name"]),
    )
