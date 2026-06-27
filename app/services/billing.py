"""Billing — bill creation with the point-in-time share snapshot, and dues.

The snapshot is load-bearing (DESIGN.md): splits are frozen at creation over the
*then-active* tenants, so a later roster change never rewrites a past month.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import DomainError, NotFound
from app.db.models import Member
from app.domain.enums import BillEventType, BillStatus
from app.domain.time import deadline_iso, now, now_iso
from app.repositories import bills as bills_repo
from app.repositories import fines as fines_repo
from app.repositories import members as members_repo
from app.services import notifications


async def create_bill(session: AsyncSession, *, type: str, total: int, month: str, payer: Member) -> int:
    """The payer declares "I paid this": record the bill (status=pending), snapshot one
    share per active tenant, open the confirmation window, and ping the other tenants so
    they can dispute. The remainder of the integer split goes to the first tenant so the
    shares sum to exactly `total`."""
    tenants = await members_repo.list_active_tenants(session)
    if not tenants:
        raise DomainError("Cannot create a bill with no active tenants to split it.")

    bill = await bills_repo.create_bill(
        session, type=type, total=total, month=month, paid_by=payer.id,
        status=BillStatus.PENDING, confirm_deadline=deadline_iso(now(), settings.bill_confirm_hours),
    )
    base, remainder = divmod(total, len(tenants))
    for i, tenant in enumerate(tenants):
        share = base + (remainder if i == 0 else 0)
        await bills_repo.add_share(session, bill_id=bill.id, member_id=tenant.id, share_amount=share)
    await bills_repo.log_event(
        session, bill_id=bill.id, type=BillEventType.CREATED, actor_id=payer.id,
        detail=f"{payer.name} declared the {type} bill paid ({total})",
    )
    others = [t for t in tenants if t.id != payer.id]
    if others:
        await notifications.bill_claimed(
            session, recipients=others, bill_id=bill.id, payer_name=payer.name,
            bill_type=type, amount=total, confirm_hours=settings.bill_confirm_hours,
        )
    return bill.id


async def dispute_bill(
    session: AsyncSession, *, bill_id: int, member: Member, reason: str | None = None
) -> None:
    """A tenant (not the payer) disputes a pending bill before its deadline. A disputed
    bill is frozen — the sweep never auto-confirms it (future: a flat vote plugs in here)."""
    bill = await bills_repo.get_bill(session, bill_id)
    if bill is None:
        raise NotFound("No such bill.")
    if bill.status != BillStatus.PENDING:
        raise DomainError("Only a bill awaiting confirmation can be disputed.")
    if bill.paid_by == member.id:
        raise DomainError("You can't dispute a bill you declared yourself.")
    if bill.confirm_deadline and bill.confirm_deadline < now_iso():
        raise DomainError("The confirmation window has already closed.")

    clean = (reason or "").strip() or None
    bill.status = BillStatus.DISPUTED
    bill.disputed_by = member.id
    bill.dispute_reason = clean
    await bills_repo.log_event(
        session, bill_id=bill.id, type=BillEventType.DISPUTED, actor_id=member.id, detail=clean,
    )
    recipients = [t for t in await members_repo.list_active_tenants(session) if t.id != member.id]
    if recipients:
        await notifications.bill_disputed(
            session, recipients=recipients, bill_id=bill.id,
            disputer_name=member.name, bill_type=bill.type, reason=clean,
        )


async def sweep_due(session: AsyncSession) -> list[int]:
    """Auto-confirm overdue, undisputed bills (lazy consensus). Idempotent + audit-logged;
    safe to rerun — `bulk_auto_confirm` only ever touches still-pending rows. Returns ids."""
    confirmed = await bills_repo.bulk_auto_confirm(session, now_iso())
    if not confirmed:
        return []
    recipients = await members_repo.list_active_tenants(session)
    for bill_id in confirmed:
        await bills_repo.log_event(
            session, bill_id=bill_id, type=BillEventType.AUTO_CONFIRMED,
            detail="confirmation window elapsed, undisputed",
        )
        bill = await bills_repo.get_bill(session, bill_id)
        if bill is not None:
            await notifications.bill_auto_confirmed(
                session, recipients=recipients, bill_id=bill_id,
                bill_type=bill.type, amount=bill.total,
            )
    return confirmed


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
