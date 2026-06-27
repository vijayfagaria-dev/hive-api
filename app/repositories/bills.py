"""Bill data access — the bill and its point-in-time shares."""

from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import Row, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models import Bill, BillEvent, BillShare, Member
from app.domain.enums import BillStatus
from app.repositories import fits_i64


async def create_bill(
    session: AsyncSession,
    *,
    type: str,
    total: int,
    month: str,
    paid_by: Optional[int],
    status: str,
    confirm_deadline: Optional[str],
) -> Bill:
    bill = Bill(
        type=type, total=total, month=month, paid_by=paid_by,
        status=status, confirm_deadline=confirm_deadline,
    )
    session.add(bill)
    await session.flush()
    return bill


async def log_event(
    session: AsyncSession,
    *,
    bill_id: int,
    type: str,
    actor_id: Optional[int] = None,
    detail: Optional[str] = None,
) -> BillEvent:
    event = BillEvent(bill_id=bill_id, type=type, actor_id=actor_id, detail=detail)
    session.add(event)
    await session.flush()
    return event


async def bulk_auto_confirm(session: AsyncSession, now_iso_str: str) -> list[int]:
    """Atomically confirm overdue, still-pending (undisputed) bills and RETURN the ids
    changed — one statement holds the write lock, so a concurrent dispute can't slip in."""
    stmt = (
        update(Bill)
        .where(
            Bill.status == BillStatus.PENDING,
            Bill.confirm_deadline.is_not(None),
            Bill.confirm_deadline < now_iso_str,
        )
        .values(status=BillStatus.CONFIRMED, resolved_at=now_iso_str)
        .returning(Bill.id)
        .execution_options(synchronize_session=False)
    )
    return [row[0] for row in (await session.execute(stmt)).all()]


async def recent_bills(session: AsyncSession, limit: int = 12) -> Sequence[Row]:
    """Recent bills with payer + disputer names, newest first (for the dashboard)."""
    payer = aliased(Member)
    disputer = aliased(Member)
    stmt = (
        select(
            Bill.id, Bill.type, Bill.total, Bill.month, Bill.status,
            Bill.paid_by, Bill.ts, Bill.confirm_deadline,
            Bill.dispute_reason, Bill.resolved_at,
            payer.name.label("payer_name"),
            disputer.name.label("disputer_name"),
        )
        .join(payer, payer.id == Bill.paid_by, isouter=True)
        .join(disputer, disputer.id == Bill.disputed_by, isouter=True)
        .order_by(Bill.ts.desc(), Bill.id.desc())
        .limit(limit)
    )
    return (await session.execute(stmt)).all()


async def add_share(
    session: AsyncSession, *, bill_id: int, member_id: int, share_amount: int
) -> BillShare:
    share = BillShare(bill_id=bill_id, member_id=member_id, share_amount=share_amount)
    session.add(share)
    return share


async def get_bill(session: AsyncSession, bill_id) -> Optional[Bill]:
    if not fits_i64(bill_id):
        return None
    return await session.get(Bill, bill_id)


async def list_shares(session: AsyncSession, bill_id: int) -> Sequence[Row]:
    """Every snapshotted share for a bill, with member names (for the bill card)."""
    stmt = (
        select(BillShare.member_id, BillShare.share_amount, BillShare.paid, Member.name)
        .join(Member, Member.id == BillShare.member_id)
        .where(BillShare.bill_id == bill_id)
        .order_by(Member.name)
    )
    return (await session.execute(stmt)).all()


async def mark_share_paid(session: AsyncSession, bill_id: int, member_id: int) -> None:
    share = await session.scalar(
        select(BillShare).where(
            BillShare.bill_id == bill_id, BillShare.member_id == member_id
        )
    )
    if share is not None:
        share.paid = True


async def list_unpaid_shares(session: AsyncSession, member_id: int) -> Sequence[Row]:
    stmt = (
        select(
            BillShare.id,
            BillShare.bill_id,
            BillShare.share_amount,
            Bill.type,
            Bill.month,
        )
        .join(Bill, Bill.id == BillShare.bill_id)
        .where(BillShare.member_id == member_id, BillShare.paid.is_(False))
        .order_by(Bill.month, Bill.type)
    )
    return (await session.execute(stmt)).all()


async def bills_owed_by(session: AsyncSession, member_id: int) -> int:
    return await session.scalar(
        select(func.coalesce(func.sum(BillShare.share_amount), 0)).where(
            BillShare.member_id == member_id, BillShare.paid.is_(False)
        )
    )
