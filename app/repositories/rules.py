"""Rule data access."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Rule
from app.repositories import fits_i64


async def get(session: AsyncSession, rule_id) -> Optional[Rule]:
    if not fits_i64(rule_id):
        return None
    return await session.get(Rule, rule_id)


async def list_all(session: AsyncSession) -> list[Rule]:
    """All active rules, grouped-friendly (category then favorites) — for the web menu."""
    return list(
        await session.scalars(
            select(Rule)
            .where(Rule.is_active.is_(True))
            .order_by(Rule.category, Rule.is_favorite.desc(), Rule.id)
        )
    )


async def list_favorites(session: AsyncSession, limit: int = 10) -> list[Rule]:
    return list(
        await session.scalars(
            select(Rule)
            .where(Rule.is_active.is_(True))
            .order_by(Rule.is_favorite.desc(), Rule.use_count.desc(), Rule.id)
            .limit(limit)
        )
    )


async def list_by_category(session: AsyncSession, category: str) -> list[Rule]:
    return list(
        await session.scalars(
            select(Rule)
            .where(Rule.category == category, Rule.is_active.is_(True))
            .order_by(Rule.use_count.desc(), Rule.id)
        )
    )


async def add(
    session: AsyncSession,
    *,
    category: str,
    text: str,
    fine_amount: int,
    is_favorite: bool = False,
    severity_tier: str = "low",
    auto_confirm: bool = True,
) -> Rule:
    rule = Rule(
        category=category,
        text=text,
        fine_amount=fine_amount,
        is_favorite=is_favorite,
        severity_tier=severity_tier,
        auto_confirm=auto_confirm,
    )
    session.add(rule)
    await session.flush()
    return rule
