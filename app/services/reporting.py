"""Reporting — pot, dues table, leaderboard, accuser-accountability, dashboard.

Read-only aggregation that composes repositories (and the billing service for
dues). Presentation math (overturn rate) lives here, not in the data layer.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import fines as fines_repo
from app.services import billing


async def pot(session: AsyncSession) -> int:
    return await fines_repo.pot_total(session)


async def owed_count(session: AsyncSession) -> int:
    return await fines_repo.owed_count(session)


async def hall_of_shame(session: AsyncSession, limit: int = 10) -> list[dict]:
    return await fines_repo.hall_of_shame(session, limit)


async def overturn(session: AsyncSession) -> list[dict]:
    """Accuser accountability per active member, with the overturn rate computed."""
    out = []
    for row in await fines_repo.overturn_rows(session):
        filed = row.filed or 0
        overturned = row.overturned or 0
        out.append(
            {
                "name": row.name,
                "filed": filed,
                "upheld": row.upheld or 0,
                "overturned": overturned,
                "overturn_rate": round(100 * overturned / filed) if filed else 0,
            }
        )
    return out


async def recent_complaints(session: AsyncSession, limit: int = 15):
    return await fines_repo.recent(session, limit)


async def dashboard(session: AsyncSession) -> dict:
    """Everything the tenant dashboard shows (raw pieces; the schema maps them)."""
    dues = [d for d in await billing.all_dues(session) if d["total"] > 0]
    overturn_rows = [o for o in await overturn(session) if o["filed"]]
    return {
        "pot": await pot(session),
        "pot_count": await owed_count(session),
        "dues": dues,
        "recent": await recent_complaints(session, 15),
        "overturn": overturn_rows,
    }
