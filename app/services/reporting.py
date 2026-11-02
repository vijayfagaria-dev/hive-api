"""Reporting — pot, dues table, leaderboard, accuser-accountability, dashboard.

Read-only aggregation that composes repositories (and the billing service for
dues). Presentation math (overturn rate) lives here, not in the data layer.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import bills as bills_repo
from app.repositories import expenses as expenses_repo
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
    # The "biggest false reporter" board: overturn() only returns members with >=1
    # overturned complaint now (the HAVING lives in the repo query), so no extra gate.
    overturn_rows = await overturn(session)
    return {
        "pot": await pot(session),
        "pot_count": await owed_count(session),
        "dues": dues,
        "recent": await recent_complaints(session, 5),  # a glance; the Feed has the full list
        "overturn": overturn_rows,
        "bills": await bills_repo.recent_bills(session),
    }


async def monthly_spending(session: AsyncSession, *, member_id: int, current: str, past: int = 6) -> list[dict]:
    """This month plus the latest `past` earlier months that had spending, newest first:
    what the flat spent, the member's share of it and what they fronted — overall and
    per category (rent included)."""
    earlier = await expenses_repo.months_with_expenses(session, upto=current, limit=past + 1)
    months = [current] + [m for m in earlier if m < current][:past]
    out = {m: {"month": m, "total": 0, "mine": 0, "paid": 0, "categories": {}} for m in months}
    for month, cat, total in await expenses_repo.totals_by_category(session, months):
        out[month]["categories"][cat] = {"category": cat, "total": int(total), "mine": 0}
        out[month]["total"] += int(total)
    for month, cat, mine in await expenses_repo.shares_by_category(session, member_id, months):
        out[month]["categories"][cat]["mine"] = int(mine)
        out[month]["mine"] += int(mine)
    for month, paid in (await expenses_repo.paid_by_month(session, member_id, months)).items():
        out[month]["paid"] = paid
    return [
        {**row, "categories": sorted(row["categories"].values(), key=lambda c: -c["total"])}
        for row in out.values()
    ]
