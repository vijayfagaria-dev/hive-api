"""Member data access."""

from __future__ import annotations

from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Member
from app.domain.enums import Role
from app.repositories import fits_i64


async def get(session: AsyncSession, member_id) -> Optional[Member]:
    if not fits_i64(member_id):
        return None
    return await session.get(Member, member_id)


async def get_by_username(session: AsyncSession, username: str) -> Optional[Member]:
    return await session.scalar(
        select(Member).where(func.lower(Member.username) == func.lower(username))
    )


async def list_active(session: AsyncSession) -> list[Member]:
    return list(
        await session.scalars(
            select(Member).where(Member.is_active.is_(True)).order_by(Member.name)
        )
    )


async def list_active_tenants(session: AsyncSession) -> list[Member]:
    return list(
        await session.scalars(
            select(Member)
            .where(Member.is_active.is_(True), Member.role == Role.TENANT)
            .order_by(Member.name)
        )
    )


async def list_all(session: AsyncSession, *, include_inactive: bool = False) -> list[Member]:
    """The household roster. Active-first, then by name; pass include_inactive to
    surface members who have left (for the admin management view)."""
    stmt = select(Member)
    if not include_inactive:
        stmt = stmt.where(Member.is_active.is_(True))
    return list(await session.scalars(stmt.order_by(Member.is_active.desc(), Member.name)))


async def count_active_with_roles(session: AsyncSession, roles: Iterable[str]) -> int:
    """How many active members hold any of these roles (used for the last-admin guard)."""
    return (
        await session.scalar(
            select(func.count())
            .select_from(Member)
            .where(Member.is_active.is_(True), Member.role.in_(list(roles)))
        )
    ) or 0


async def eligible_voters(
    session: AsyncSession, accuser_id: int, accused_id: int
) -> list[Member]:
    """Active members who may vote: everyone except the accuser and the accused."""
    return list(
        await session.scalars(
            select(Member)
            .where(Member.is_active.is_(True), Member.id.notin_([accuser_id, accused_id]))
            .order_by(Member.name)
        )
    )


async def add(session: AsyncSession, *, name: str, role: str = Role.TENANT) -> Member:
    member = Member(name=name, role=role)
    session.add(member)
    await session.flush()
    return member


async def register(session: AsyncSession, *, username: str, password_hash: str) -> Member:
    """Self-registration: an active guest whose username doubles as the name."""
    member = Member(name=username, username=username, password_hash=password_hash, role=Role.GUEST)
    session.add(member)
    await session.flush()
    return member


async def create(
    session: AsyncSession, *, username: str, password_hash: str, role: str, name: Optional[str] = None
) -> Member:
    """Create a member with an explicit role + display name (self-register or invite redeem)."""
    member = Member(
        name=(name or username), username=username, password_hash=password_hash, role=role
    )
    session.add(member)
    await session.flush()
    return member
