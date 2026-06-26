"""Invitation data access."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Invitation
from app.domain.enums import InvitationStatus
from app.repositories import fits_i64


async def insert(
    session: AsyncSession,
    *,
    token: str,
    role: str,
    invited_by: int,
    expires_at: str,
    name: Optional[str] = None,
    email: Optional[str] = None,
) -> Invitation:
    inv = Invitation(
        token=token, role=role, invited_by=invited_by, expires_at=expires_at,
        name=name, email=email,
    )
    session.add(inv)
    await session.flush()
    return inv


async def get(session: AsyncSession, invitation_id) -> Optional[Invitation]:
    if not fits_i64(invitation_id):
        return None
    return await session.get(Invitation, invitation_id)


async def get_by_token(session: AsyncSession, token: str) -> Optional[Invitation]:
    return await session.scalar(select(Invitation).where(Invitation.token == token))


async def list_pending(session: AsyncSession) -> list[Invitation]:
    return list(
        await session.scalars(
            select(Invitation)
            .where(Invitation.status == InvitationStatus.PENDING)
            .order_by(Invitation.created_at.desc())
        )
    )


async def count_since(session: AsyncSession, invited_by: int, since_iso: str) -> int:
    """Invites minted by this member since a cutoff (anti-spam window)."""
    return (
        await session.scalar(
            select(func.count())
            .select_from(Invitation)
            .where(Invitation.invited_by == invited_by, Invitation.created_at >= since_iso)
        )
    ) or 0
