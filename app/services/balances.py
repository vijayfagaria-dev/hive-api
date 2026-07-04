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


# --- Settle-up graph (peer-to-peer only; always sums to zero) ----------------

async def settle_net_for(session: AsyncSession, member: Member) -> int:
    """A member's PEER-TO-PEER balance: shared expenses + member<->member payments only.

        settle_net = expensesPaid − expenseShare + sent − received

    This component always sums to zero across members (each expense's shares sum to its
    amount; each member<->member payment credits one and debits the other), so it — and
    ONLY it — can be settled by transfers. The one-sided terms in `net_for` (unpaid fines
    owed to the pot, ledger advances/broker/deposit, house/landlord payments) are excluded:
    those are cleared via the pay screen / ledger, never peer settle-up. This is what makes
    the simplifier's zero-sum precondition hold (fixing the guaranteed HTTP 500)."""
    paid = await expenses_repo.paid_by(session, member.id)
    share = await expenses_repo.owed_by(session, member.id)
    received = await expenses_repo.received_by(session, member.id)
    sent = await expenses_repo.sent_by(session, member.id)
    return paid - share + sent - received


async def settle_balances(session: AsyncSession) -> list[dict]:
    """Peer-to-peer net per active member (the settle-up worklist input)."""
    rows = []
    for m in await members_repo.list_active(session):
        rows.append({"memberId": m.id, "name": m.name, "net": await settle_net_for(session, m)})
    return rows
