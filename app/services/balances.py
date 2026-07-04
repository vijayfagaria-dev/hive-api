"""Derived balances — the single source of truth for "what I owe / am owed".

Every balance is a pure fold over facts; nothing is stored. The payer is credited the
full amount they fronted (`expensesPaid`) and debited only their own split share
(`expenseShare`), so a payer can never be shown owing their own share — the old bug is
arithmetic-impossible now. Fines and the ledger (advances/broker/deposit/penalty/payout)
remain explicit summands.

    net = expensesPaid − expenseShare + sent − received + ledgerBalance − finesOwed

(a payment you SEND to settle a debt raises your net toward zero; one you RECEIVE lowers it.)
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Member
from app.repositories import expenses as expenses_repo
from app.repositories import fines as fines_repo
from app.repositories import ledger as ledger_repo
from app.repositories import members as members_repo


async def net_for(session: AsyncSession, member: Member) -> dict:
    paid = await expenses_repo.paid_by(session, member.id)
    share = await expenses_repo.owed_by(session, member.id)
    received = await expenses_repo.received_by(session, member.id)
    sent = await expenses_repo.sent_by(session, member.id)
    ledger_balance = await ledger_repo.balance(session, member.id)
    fines_owed = await fines_repo.fines_owed_by(session, member.id)
    net = paid - share + sent - received + ledger_balance - fines_owed
    return {
        "memberId": member.id,
        "net": net,
        "owes": max(0, -net),
        "owed": max(0, net),
        "expensesPaid": paid,
        "expenseShare": share,
        "received": received,
        "sent": sent,
        "ledgerBalance": ledger_balance,
        "finesOwed": fines_owed,
    }


async def all_balances(session: AsyncSession) -> list[dict]:
    """Net per active member, most-in-debt first — the 'who's up, who's down' board."""
    rows = []
    for m in await members_repo.list_active(session):
        n = await net_for(session, m)
        rows.append({"memberId": m.id, "name": m.name, "role": m.role, "net": n["net"]})
    return sorted(rows, key=lambda r: r["net"])


def balances_map(rows: list[dict]) -> dict[int, int]:
    """member_id -> net, for the debt simplifier (drops exact-zero members)."""
    return {r["memberId"]: r["net"] for r in rows if r["net"] != 0}
