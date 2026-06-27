"""Money-ledger data access — ledger entries + settlement records."""

from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import Row, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LedgerEntry, Member, Settlement


async def add_entry(
    session: AsyncSession,
    *,
    member_id: int,
    type: str,
    amount: int,
    reason: str,
    period: Optional[str] = None,
    settlement_id: Optional[int] = None,
    created_by: Optional[int] = None,
) -> LedgerEntry:
    entry = LedgerEntry(
        member_id=member_id, type=type, amount=amount, reason=reason,
        period=period, settlement_id=settlement_id, created_by=created_by,
    )
    session.add(entry)
    await session.flush()
    return entry


async def balance(session: AsyncSession, member_id: int) -> int:
    """Signed ledger balance for one member (+ flat owes them, - they owe)."""
    return await session.scalar(
        select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
            LedgerEntry.member_id == member_id
        )
    )


async def list_for_member(session: AsyncSession, member_id: int) -> list[LedgerEntry]:
    return list(
        await session.scalars(
            select(LedgerEntry)
            .where(LedgerEntry.member_id == member_id)
            .order_by(LedgerEntry.created_at.desc(), LedgerEntry.id.desc())
        )
    )


async def list_recent(session: AsyncSession, limit: int = 60) -> Sequence[Row]:
    """All ledger entries with member names — for the admin ledger view."""
    stmt = (
        select(
            LedgerEntry.id, LedgerEntry.member_id, LedgerEntry.type, LedgerEntry.amount,
            LedgerEntry.reason, LedgerEntry.period, LedgerEntry.created_at,
            Member.name.label("member_name"),
        )
        .join(Member, Member.id == LedgerEntry.member_id)
        .order_by(LedgerEntry.created_at.desc(), LedgerEntry.id.desc())
        .limit(limit)
    )
    return (await session.execute(stmt)).all()


# --- settlements -----------------------------------------------------------

async def add_settlement(
    session: AsyncSession,
    *,
    period_from: str,
    period_to: str,
    monthly_rent: int,
    pot_collected: int,
    applied_to_rent: int,
    leftover: int,
    note: Optional[str] = None,
    created_by: Optional[int] = None,
) -> Settlement:
    s = Settlement(
        period_from=period_from, period_to=period_to, monthly_rent=monthly_rent,
        pot_collected=pot_collected, applied_to_rent=applied_to_rent, leftover=leftover,
        note=note, created_by=created_by,
    )
    session.add(s)
    await session.flush()
    return s


async def latest_settlement(session: AsyncSession) -> Optional[Settlement]:
    return await session.scalar(
        select(Settlement).order_by(Settlement.period_to.desc(), Settlement.id.desc()).limit(1)
    )


async def list_settlements(session: AsyncSession, limit: int = 24) -> list[Settlement]:
    return list(
        await session.scalars(
            select(Settlement).order_by(Settlement.period_to.desc(), Settlement.id.desc()).limit(limit)
        )
    )
