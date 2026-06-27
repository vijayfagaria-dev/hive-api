"""Money ledger — one-time charges (broker/deposit), credits (advance/payment), and
manual adjustments. Admin-only. Everything is a signed `ledger_entries` row that rolls
up into each member's running balance (see services/money.py)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Unprocessable
from app.db.models import LedgerEntry, Member
from app.domain import permissions
from app.domain.enums import LedgerEntryType, Permission
from app.domain.money import split_by_ratio
from app.repositories import ledger as ledger_repo
from app.repositories import members as members_repo

_CHARGE_TYPES = {LedgerEntryType.BROKER.value, LedgerEntryType.DEPOSIT.value}
_CREDIT_TYPES = {LedgerEntryType.ADVANCE.value, LedgerEntryType.DEPOSIT.value, LedgerEntryType.PAYOUT.value}


async def add_charge(
    session: AsyncSession, *, actor: Member, type: str, total: int, reason: str, split: str = "ratio"
) -> list[LedgerEntry]:
    """Charge a one-time cost (broker/deposit) to the active tenants — a debit each, split
    by rent ratio or equally. Each tenant's share is recorded so 'My Money' shows the why."""
    permissions.require(actor, Permission.MANAGE_USERS)
    if type not in _CHARGE_TYPES:
        raise Unprocessable(f"Charge type must be one of {sorted(_CHARGE_TYPES)}.")
    if total <= 0:
        raise Unprocessable("Amount must be positive.")
    tenants = await members_repo.list_active_tenants(session)
    if not tenants:
        raise Unprocessable("No active tenants to charge.")
    if split == "ratio":
        weights = [t.rent_share_pct or 0 for t in tenants]
        if sum(weights) != 100:
            raise Unprocessable("Set rent shares (total 100%) before a ratio split.")
    else:
        weights = [1] * len(tenants)
    amounts = split_by_ratio(total, weights)
    entries = []
    for tenant, amt in zip(tenants, amounts):
        entries.append(
            await ledger_repo.add_entry(
                session, member_id=tenant.id, type=type, amount=-amt,
                reason=reason, period="opening", created_by=actor.id,
            )
        )
    return entries


async def add_credit(
    session: AsyncSession, *, actor: Member, member_id: int, type: str, amount: int, reason: str
) -> LedgerEntry:
    """Record money a member has paid (advance, or a payment toward their dues) — a credit."""
    permissions.require(actor, Permission.MANAGE_USERS)
    if type not in _CREDIT_TYPES:
        raise Unprocessable(f"Credit type must be one of {sorted(_CREDIT_TYPES)}.")
    if amount <= 0:
        raise Unprocessable("Amount must be positive.")
    if await members_repo.get(session, member_id) is None:
        raise Unprocessable("No such member.")
    return await ledger_repo.add_entry(
        session, member_id=member_id, type=type, amount=amount, reason=reason, created_by=actor.id
    )


async def add_adjustment(
    session: AsyncSession, *, actor: Member, member_id: int, amount: int, reason: str
) -> LedgerEntry:
    """A manual signed correction (+ credit / - debit)."""
    permissions.require(actor, Permission.MANAGE_USERS)
    if amount == 0:
        raise Unprocessable("Adjustment can't be zero.")
    if await members_repo.get(session, member_id) is None:
        raise Unprocessable("No such member.")
    return await ledger_repo.add_entry(
        session, member_id=member_id, type=LedgerEntryType.ADJUSTMENT, amount=amount,
        reason=reason, created_by=actor.id,
    )
