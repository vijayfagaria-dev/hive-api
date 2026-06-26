"""Rule-version data access — the immutable rule-book history."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RuleVersion
from app.repositories import fits_i64


async def next_version_number(session: AsyncSession, rule_id: int) -> int:
    current = await session.scalar(
        select(func.coalesce(func.max(RuleVersion.version_number), 0)).where(
            RuleVersion.rule_id == rule_id
        )
    )
    return (current or 0) + 1


async def insert(session: AsyncSession, **fields) -> RuleVersion:
    version = RuleVersion(**fields)
    session.add(version)
    await session.flush()
    return version


async def list_for(session: AsyncSession, rule_id: int) -> list[RuleVersion]:
    return list(
        await session.scalars(
            select(RuleVersion)
            .where(RuleVersion.rule_id == rule_id)
            .order_by(RuleVersion.version_number.desc())
        )
    )


async def get(session: AsyncSession, version_id) -> Optional[RuleVersion]:
    if not fits_i64(version_id):
        return None
    return await session.get(RuleVersion, version_id)
