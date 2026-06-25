"""Quick checks: /pot, /dues, /rules — plus the pay buttons surfaced by /dues."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from .. import fines as fines_service
from .. import queries
from . import callbacks as cb
from . import formatting as fmt
from . import keyboards as kb
from .common import require_member, safe_edit

router = Router(name="checks")


@router.message(Command("pot"))
async def cmd_pot(message: Message, db) -> None:
    total = await queries.pot_total(db)
    count = await queries.owed_fine_count(db)
    await message.answer(fmt.pot_text(total, count))


async def _render_dues(db, member):
    """(text, markup) for a member's current dues."""
    dues = await queries.member_dues(db, member["id"])
    fines = await queries.list_unpaid_owed_fines(db, member["id"])
    shares = await queries.list_unpaid_shares(db, member["id"])
    text = fmt.dues_text(name=member["name"], fines=fines, shares=shares, total=dues["total"])
    markup = kb.dues_kb(fines, shares) if dues["total"] else None
    return text, markup


@router.message(Command("dues"))
async def cmd_dues(message: Message, command: CommandObject, db, member) -> None:
    if not await require_member(message, member):
        return
    if (command.args or "").strip().lower() == "all":
        await message.answer(fmt.all_dues_text(await queries.all_dues(db)))
        return
    text, markup = await _render_dues(db, member)
    await message.answer(text, reply_markup=markup)


@router.callback_query(cb.FinePay.filter())
async def cb_fine_pay(callback: CallbackQuery, callback_data: cb.FinePay, db, member) -> None:
    if not await require_member(callback, member):
        return
    fine = await queries.get_fine(db, callback_data.fine_id)
    if fine is None or fine["member_id"] != member["id"]:
        await callback.answer("That's not your fine to pay.", show_alert=True)
        return
    try:
        changed = await fines_service.mark_paid(db, callback_data.fine_id)
    except fines_service.FineError as e:
        await callback.answer(str(e), show_alert=True)
        return
    if not changed:
        await callback.answer("Already paid.")
        return
    await callback.answer("Marked paid ✅")
    text, markup = await _render_dues(db, member)
    await safe_edit(callback.message, text, markup)


@router.callback_query(cb.DuesShare.filter())
async def cb_dues_share(callback: CallbackQuery, callback_data: cb.DuesShare, db, member) -> None:
    if not await require_member(callback, member):
        return
    await queries.mark_share_paid(db, callback_data.bill_id, member["id"])
    await callback.answer("Marked paid ✅")
    text, markup = await _render_dues(db, member)
    await safe_edit(callback.message, text, markup)


@router.message(Command("rules"))
async def cmd_rules(message: Message, db) -> None:
    favorites = await queries.list_favorite_rules(db)
    categories = await queries.list_categories(db)
    await message.answer(
        fmt.rules_overview_text(favorites, categories),
        reply_markup=kb.rules_categories_kb(categories),
    )


@router.callback_query(cb.RulesCat.filter())
async def cb_rules_cat(callback: CallbackQuery, callback_data: cb.RulesCat, db) -> None:
    rules = await queries.list_rules_by_category(db, callback_data.category)
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(fmt.rules_category_text(callback_data.category, rules))
