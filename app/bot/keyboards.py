"""Inline keyboard builders. Each takes plain rows and returns InlineKeyboardMarkup.

Rule selection never dumps all 100 rules (DESIGN/BR-020): favorites + browse +
search. Buttons carry typed callback data from callbacks.py.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Sequence

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import callbacks as cb
from .formatting import bill_label, rupees


def _short(text: str, n: int = 34) -> str:
    text = text.strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def claim_kb(unlinked: Sequence[Mapping]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for m in unlinked:
        b.button(text=f"That's me — {m['name']}", callback_data=cb.Claim(member_id=m["id"]))
    b.adjust(1)
    return b.as_markup()


def fine_rules_kb(rules: Sequence[Mapping], *, with_browse: bool = True) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for r in rules:
        b.button(
            text=f"{_short(r['text'])} · {rupees(r['fine_amount'])}",
            callback_data=cb.FineRule(rule_id=r["id"]),
        )
    b.adjust(1)
    if with_browse:
        b.row()  # start a new row for the browse button
        b.button(text="📂 Browse categories", callback_data=cb.FINE_CATS)
    return b.as_markup()


def fine_categories_kb(categories: Iterable[str]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for c in categories:
        b.button(text=c, callback_data=cb.FineCat(category=c))
    b.adjust(2)
    return b.as_markup()


def fine_who_kb(rule_id: int, members: Sequence[Mapping]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for m in members:
        b.button(
            text=m["name"], callback_data=cb.FineWho(rule_id=rule_id, member_id=m["id"])
        )
    b.adjust(2)
    return b.as_markup()


def fine_card_kb(fine_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⚖️ Dispute", callback_data=cb.FineDispute(fine_id=fine_id))
    return b.as_markup()


def dues_kb(fines: Sequence[Mapping], shares: Sequence[Mapping]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for f in fines:
        b.button(
            text=f"Pay fine: {rupees(f['amount'])}",
            callback_data=cb.FinePay(fine_id=f["id"]),
        )
    for s in shares:
        # DuesShare (not BillShare): the handler marks only the CALLER's own share
        # and re-renders the private dues view — never the shared bill card.
        b.button(
            text=f"Pay {bill_label(s['type'])} {rupees(s['share_amount'])}",
            callback_data=cb.DuesShare(bill_id=s["bill_id"]),
        )
    b.adjust(1)
    return b.as_markup()


def bill_card_kb(bill_id: int, shares: Sequence[Mapping]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for s in shares:
        if not s["paid"]:
            b.button(
                text=f"✅ {s['name']} paid",
                callback_data=cb.BillShare(bill_id=bill_id, member_id=s["member_id"]),
            )
    b.adjust(2)
    return b.as_markup()


def rules_categories_kb(categories: Iterable[str]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for c in categories:
        b.button(text=c, callback_data=cb.RulesCat(category=c))
    b.adjust(2)
    return b.as_markup()
