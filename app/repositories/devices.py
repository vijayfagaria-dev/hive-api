"""Device data access — provider-agnostic push targets (Web Push / FCM / APNS)."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Device
from app.domain.time import now_iso


async def upsert(
    session: AsyncSession, *, member_id: int, provider: str, platform: str, token: str,
    p256dh: Optional[str] = None, auth: Optional[str] = None,
) -> None:
    """Store or re-point a device by its token. A rotated/re-registered token just updates
    the owner + keys in place — never rejected (FCM tokens rotate; unlike the legacy
    endpoint UNIQUE, we upsert rather than error)."""
    existing = await session.scalar(select(Device).where(Device.token == token))
    if existing is None:
        session.add(Device(
            member_id=member_id, provider=provider, platform=platform, token=token,
            p256dh=p256dh, auth=auth,
        ))
    else:
        existing.member_id = member_id
        existing.provider = provider
        existing.platform = platform
        existing.p256dh = p256dh
        existing.auth = auth
        existing.active = True
        existing.last_seen = now_iso()


async def list_for(session: AsyncSession, member_id: int, provider: str) -> list[Device]:
    return list(await session.scalars(
        select(Device).where(
            Device.member_id == member_id, Device.provider == provider, Device.active.is_(True)
        )
    ))


async def delete_by_token(session: AsyncSession, token: str) -> None:
    await session.execute(delete(Device).where(Device.token == token))
