"""Member audit-trail data access (append-only)."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MemberEvent


async def log_event(
    session: AsyncSession,
    *,
    member_id: int,
    type: str,
    actor_id: Optional[int] = None,
    detail: Optional[str] = None,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
) -> MemberEvent:
    event = MemberEvent(
        member_id=member_id, type=type, actor_id=actor_id, detail=detail,
        old_value=old_value, new_value=new_value,
    )
    session.add(event)
    await session.flush()
    return event


async def list_for(session: AsyncSession, member_id: int) -> list[MemberEvent]:
    return list(
        await session.scalars(
            select(MemberEvent).where(MemberEvent.member_id == member_id).order_by(MemberEvent.ts)
        )
    )
