"""Bill data access — the bill and its point-in-time shares."""

from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import Row, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bill, BillShare, Member
from app.repositories import fits_i64


async def create_bill(
    session: AsyncSession, *, type: str, total: int, month: str, paid_by: Optional[int]
) -> Bill:
    bill = Bill(type=type, total=total, month=month, paid_by=paid_by)
    session.add(bill)
    await session.flush()
    return bill


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
