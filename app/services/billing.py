"""Billing — bill creation with the point-in-time share snapshot, and dues.

The snapshot is load-bearing (DESIGN.md): splits are frozen at creation over the
*then-active* tenants, so a later roster change never rewrites a past month.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError
from app.repositories import bills as bills_repo
from app.repositories import fines as fines_repo
from app.repositories import members as members_repo


async def create_bill(
    session: AsyncSession, *, type: str, total: int, month: str, paid_by: int | None
) -> int:
    """Record a bill AND snapshot one share per active tenant. The integer-division
    remainder goes to the first tenant so shares sum to exactly `total`."""
    tenants = await members_repo.list_active_tenants(session)
    if not tenants:
        raise DomainError("Cannot create a bill with no active tenants to split it.")

    bill = await bills_repo.create_bill(session, type=type, total=total, month=month, paid_by=paid_by)
    base, remainder = divmod(total, len(tenants))
    for i, tenant in enumerate(tenants):
        share = base + (remainder if i == 0 else 0)
        await bills_repo.add_share(session, bill_id=bill.id, member_id=tenant.id, share_amount=share)
    return bill.id


async def mark_share_paid(session: AsyncSession, bill_id: int, member_id: int) -> None:
    await bills_repo.mark_share_paid(session, bill_id, member_id)


async def member_dues(session: AsyncSession, member_id: int) -> dict:
    """What one member owes: unpaid owed fines + unpaid bill shares."""
    fines_owed = await fines_repo.fines_owed_by(session, member_id)
    bills_owed = await bills_repo.bills_owed_by(session, member_id)
    return {"fines": fines_owed, "bills": bills_owed, "total": fines_owed + bills_owed}


async def all_dues(session: AsyncSession) -> list[dict]:
    """Dues per active member, biggest debtor first."""
    rows = []
    for member in await members_repo.list_active(session):
        dues = await member_dues(session, member.id)
        rows.append({"member_id": member.id, "name": member.name, **dues})
    return sorted(rows, key=lambda r: r["total"], reverse=True)
