"""The /bill flow — log a recurring bill and snapshot each tenant's share.

Stateless: everything comes in as command args, so there's no FSM.
  /bill <type> <amount> [YYYY-MM]      e.g. /bill electricity 2400

Share-paying from the resulting card re-renders the card. (Paying YOUR share from
/dues is a separate callback handled in checks.py so it re-renders dues instead.)
"""

from __future__ import annotations

import re

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from .. import queries
from ..db import now
from . import callbacks as cb
from . import formatting as fmt
from . import keyboards as kb
from .common import require_member, safe_edit

router = Router(name="bill")

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")  # YYYY-MM, month 01–12
_USAGE = (
    "Usage: /bill <type> <amount> [YYYY-MM]\n"
    "  types: " + ", ".join(queries.BILL_TYPES) + "\n"
    "  e.g. /bill electricity 2400"
)


@router.message(Command("bill"))
async def cmd_bill(message: Message, command: CommandObject, db, member) -> None:
    if not await require_member(message, member):
        return
    parts = (command.args or "").split()
    if len(parts) < 2:
        await message.answer(_USAGE)
        return

    bill_type = parts[0].lower()
    if bill_type not in queries.BILL_TYPES:
        await message.answer(f"Unknown bill type “{parts[0]}”.\n{_USAGE}")
        return

    try:
        amount = int(parts[1])
    except ValueError:
        await message.answer("Amount must be a whole number of rupees.\n" + _USAGE)
        return
    if amount <= 0:
        await message.answer("Amount must be positive.")
        return

    month = parts[2] if len(parts) >= 3 else now().strftime("%Y-%m")
    if not _MONTH_RE.match(month):
        await message.answer("Month must look like 2026-06 (month 01–12).")
        return

    try:
        bill_id = await queries.create_bill_with_shares(
            db, bill_type, amount, month, paid_by=member["id"]
        )
    except ValueError as e:  # e.g. no active tenants to split across
        await message.answer(str(e))
        return

    shares = await queries.list_bill_shares(db, bill_id)
    await message.answer(
        fmt.bill_card_text(bill_type=bill_type, total=amount, month=month, shares=shares),
        reply_markup=kb.bill_card_kb(bill_id, shares),
    )


@router.callback_query(cb.BillShare.filter())
async def cb_bill_share(callback: CallbackQuery, callback_data: cb.BillShare, db, member) -> None:
    if not await require_member(callback, member):
        return
    await queries.mark_share_paid(db, callback_data.bill_id, callback_data.member_id)
    await callback.answer("Marked paid ✅")
    bill = await queries.get_bill(db, callback_data.bill_id)
    if bill is None:
        return
    shares = await queries.list_bill_shares(db, callback_data.bill_id)
    # Once everyone's paid there are no buttons left — drop the keyboard entirely,
    # otherwise the edit carries an empty markup and Telegram rejects it.
    markup = (
        kb.bill_card_kb(callback_data.bill_id, shares)
        if any(not s["paid"] for s in shares)
        else None
    )
    await safe_edit(
        callback.message,
        fmt.bill_card_text(
            bill_type=bill["type"], total=bill["total"], month=bill["month"], shares=shares
        ),
        markup,
    )
