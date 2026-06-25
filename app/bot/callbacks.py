"""Typed inline-button callback data (aiogram CallbackData factories).

Each button encodes everything the next step needs, so flows stay stateless.
Keep payloads small (Telegram caps callback_data at 64 bytes) — we only ever
pack small ints and short category slugs (no ':' in category names).

Fixed, no-argument buttons use plain strings instead of a factory:
  FINE_CATS = "fine:cats"   -> open the category list inside the /fine flow
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData

# Plain-string callbacks (no payload).
FINE_CATS = "fine:cats"


class Claim(CallbackData, prefix="claim"):
    """Onboarding: a new user claims an unlinked tenant record as theirs."""

    member_id: int


class FineRule(CallbackData, prefix="frule"):
    """/fine: a rule was picked; next show the accused picker."""

    rule_id: int


class FineCat(CallbackData, prefix="fcat"):
    """/fine: drill into a category's rules."""

    category: str


class FineWho(CallbackData, prefix="fwho"):
    """/fine: the accused was picked; create the fine."""

    rule_id: int
    member_id: int


class FineDispute(CallbackData, prefix="fdis"):
    """One-tap dispute on a fine card."""

    fine_id: int


class FinePay(CallbackData, prefix="fpay"):
    """Mark a fine paid (from /dues)."""

    fine_id: int


class BillShare(CallbackData, prefix="bshr"):
    """Mark a bill share paid from a BILL CARD (re-renders the bill card)."""

    bill_id: int
    member_id: int


class DuesShare(CallbackData, prefix="dshr"):
    """Mark the caller's own bill share paid from /dues (re-renders dues)."""

    bill_id: int


class RulesCat(CallbackData, prefix="rcat"):
    """/rules: browse a category (read-only)."""

    category: str
