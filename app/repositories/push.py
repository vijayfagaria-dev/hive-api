"""Web Push subscription data access."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PushSubscription
from app.domain.time import now_iso


async def upsert(
    session: AsyncSession, *, member_id: int, endpoint: str, p256dh: str, auth: str
) -> None:
    """Store or re-point a subscription. `endpoint` is unique, so re-subscribing
    the same device updates the keys + owner in place."""
    existing = await session.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == endpoint)
    )
    if existing is None:
        session.add(
            PushSubscription(member_id=member_id, endpoint=endpoint, p256dh=p256dh, auth=auth)
        )
    else:
        existing.member_id = member_id
        existing.p256dh = p256dh
        existing.auth = auth
        existing.ts = now_iso()


async def list_for(session: AsyncSession, member_id: int) -> list[PushSubscription]:
    return list(
        await session.scalars(
            select(PushSubscription).where(PushSubscription.member_id == member_id)
        )
    )


async def delete_by_endpoint(session: AsyncSession, endpoint: str) -> None:
    await session.execute(
        delete(PushSubscription).where(PushSubscription.endpoint == endpoint)
    )
