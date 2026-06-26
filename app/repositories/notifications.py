"""Notification data access (the in-app feed)."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Notification


async def insert(
    session: AsyncSession,
    *,
    member_id: int,
    kind: str,
    title: str,
    body: Optional[str] = None,
    fine_id: Optional[int] = None,
    proposal_id: Optional[int] = None,
) -> Notification:
    notification = Notification(
        member_id=member_id, kind=kind, title=title, body=body,
        fine_id=fine_id, proposal_id=proposal_id,
    )
    session.add(notification)
    await session.flush()
    return notification


async def list_for(
    session: AsyncSession, member_id: int, limit: int = 30, unread_only: bool = False
) -> list[Notification]:
    stmt = select(Notification).where(Notification.member_id == member_id)
    if unread_only:
        stmt = stmt.where(Notification.read.is_(False))
    stmt = stmt.order_by(Notification.ts.desc(), Notification.id.desc()).limit(limit)
    return list(await session.scalars(stmt))


async def unread_count(session: AsyncSession, member_id: int) -> int:
    return await session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.member_id == member_id, Notification.read.is_(False))
    )


async def mark_read(session: AsyncSession, member_id: int, notif_id: int) -> bool:
    """Mark one notification read — scoped to its owner. True iff a row flipped."""
    result = await session.execute(
        update(Notification)
        .where(
            Notification.id == notif_id,
            Notification.member_id == member_id,
            Notification.read.is_(False),
        )
        .values(read=True)
    )
    return result.rowcount > 0


async def mark_all_read(session: AsyncSession, member_id: int) -> int:
    result = await session.execute(
        update(Notification)
        .where(Notification.member_id == member_id, Notification.read.is_(False))
        .values(read=True)
    )
    return result.rowcount
