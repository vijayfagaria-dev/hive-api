"""My Money — one transparent per-member statement over the SINGLE balance authority.

The net is delegated to `services/balances.py` (the sole source of truth for "what I owe /
am owed": shared expenses + member<->member payments + the ledger + unpaid fines). The
legacy *bills* path was retired from the money net — recurring costs are expenses now — so
the two money screens (`/money` and `/api/balances`) can no longer diverge. The fine pot
("the jar") is a separate concern (fines + settlements.py) and is untouched here.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Member
from app.repositories import fines as fines_repo
from app.repositories import ledger as ledger_repo
from app.services import balances


async def statement(session: AsyncSession, member: Member) -> dict:
    """The logged-in member's full money picture.

    `net` > 0 → the flat owes them; `net` < 0 → they owe the flat. Same net the admin
    balances board shows (both come from `balances.net_for`)."""
    n = await balances.net_for(session, member)
    unpaid_fines = await fines_repo.list_unpaid_owed(session, member.id)
    entries = await ledger_repo.list_for_member(session, member.id)

    return {
        "memberId": member.id,
        "rentSharePct": member.rent_share_pct,
        "net": n["net"],
        "owes": n["owes"],
        "owed": n["owed"],
        "finesOwed": n["finesOwed"],
        "expensesPaid": n["expensesPaid"],
        "expenseShare": n["expenseShare"],
        "received": n["received"],
        "sent": n["sent"],
        "ledgerBalance": n["ledgerBalance"],
        "fines": [{"id": r.id, "amount": r.amount, "rule": r.rule_text} for r in unpaid_fines],
        "ledger": [
            {"id": e.id, "type": e.type, "amount": e.amount, "reason": e.reason, "ts": e.created_at}
            for e in entries
        ],
    }


async def all_balances(session: AsyncSession) -> list[dict]:
    """Net balance per active member — delegated to the single authority so this admin
    overview and the per-member statement can never disagree."""
    return await balances.all_balances(session)
