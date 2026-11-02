"""One-time-code challenge data access."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OtpChallenge
from app.domain.enums import OtpPurpose


async def insert(session: AsyncSession, **fields) -> OtpChallenge:
    challenge = OtpChallenge(**fields)
    session.add(challenge)
    await session.flush()
    return challenge


def _open(purpose: str, email: str, member_id: Optional[int]):
    stmt = select(OtpChallenge).where(
        OtpChallenge.purpose == purpose,
        OtpChallenge.email == email,
        OtpChallenge.consumed_at.is_(None),
    )
    if member_id is not None:  # email-change codes belong to the member who asked
        stmt = stmt.where(OtpChallenge.member_id == member_id)
    return stmt


async def latest_open(
    session: AsyncSession, purpose: str, email: str, member_id: Optional[int] = None
) -> Optional[OtpChallenge]:
    """The newest not-yet-consumed challenge for this flow + address (may be expired)."""
    return await session.scalar(
        _open(purpose, email, member_id).order_by(OtpChallenge.id.desc()).limit(1)
    )


async def list_open(
    session: AsyncSession, purpose: str, email: str, member_id: Optional[int] = None
) -> list[OtpChallenge]:
    return list(await session.scalars(_open(purpose, email, member_id)))


async def sends_since(session: AsyncSession, purpose: str, email: str, since_iso: str) -> int:
    """Codes mailed to this address for this flow since a cutoff (anti mail-bombing)."""
    return (
        await session.scalar(
            select(func.coalesce(func.sum(OtpChallenge.send_count), 0)).where(
                OtpChallenge.purpose == purpose,
                OtpChallenge.email == email,
                OtpChallenge.last_sent_at >= since_iso,
            )
        )
    ) or 0


async def get_by_reset_token(session: AsyncSession, token_hash: str) -> Optional[OtpChallenge]:
    return await session.scalar(
        select(OtpChallenge).where(
            OtpChallenge.purpose == OtpPurpose.PASSWORD_RESET,
            OtpChallenge.reset_token_hash == token_hash,
        )
    )


async def purge_stale(session: AsyncSession, before_iso: str) -> int:
    """Drop challenges that expired (and whose reset token expired) before the cutoff."""
    result = await session.execute(
        delete(OtpChallenge).where(
            OtpChallenge.expires_at < before_iso,
            (OtpChallenge.reset_expires_at.is_(None)) | (OtpChallenge.reset_expires_at < before_iso),
        )
    )
    return result.rowcount or 0
