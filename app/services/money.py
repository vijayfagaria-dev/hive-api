"""My Money — one transparent per-member statement that unifies everything owed/paid.

Pulls together unpaid fines, unpaid bill shares, and the ledger balance (advances,
deposit, broker, settlement payouts, penalties) into a single net figure plus the
line items behind it, so a flatmate never has to guess what they owe or why.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Member
from app.repositories import bills as bills_repo
from app.repositories import fines as fines_repo
from app.repositories import ledger as ledger_repo
from app.repositories import members as members_repo


async def statement(session: AsyncSession, member: Member) -> dict:
    """The logged-in member's full money picture.

    `net` > 0 → the flat owes them; `net` < 0 → they owe the flat.
    """
    fines_owed = await fines_repo.fines_owed_by(session, member.id)
    unpaid_fines = await fines_repo.list_unpaid_owed(session, member.id)
    bills_owed = await bills_repo.bills_owed_by(session, member.id)
    unpaid_shares = await bills_repo.list_unpaid_shares(session, member.id)
    entries = await ledger_repo.list_for_member(session, member.id)

    ledger_balance = sum(e.amount for e in entries)
    net = ledger_balance - fines_owed - bills_owed

    return {
        "memberId": member.id,
        "rentSharePct": member.rent_share_pct,
        "net": net,
        "owes": max(0, -net),
        "owed": max(0, net),
        "finesOwed": fines_owed,
        "billsOwed": bills_owed,
        "ledgerBalance": ledger_balance,
        "fines": [{"id": r.id, "amount": r.amount, "rule": r.rule_text} for r in unpaid_fines],
        "bills": [
            {"billId": r.bill_id, "type": r.type, "month": r.month, "amount": r.share_amount}
            for r in unpaid_shares
        ],
        "ledger": [
            {"id": e.id, "type": e.type, "amount": e.amount, "reason": e.reason, "ts": e.created_at}
            for e in entries
        ],
    }


async def all_balances(session: AsyncSession) -> list[dict]:
    """Net balance per active member — the admin overview ('who's up, who's down')."""
    rows = []
    for m in await members_repo.list_active(session):
        fines_owed = await fines_repo.fines_owed_by(session, m.id)
        bills_owed = await bills_repo.bills_owed_by(session, m.id)
        ledger_balance = await ledger_repo.balance(session, m.id)
        net = ledger_balance - fines_owed - bills_owed
        rows.append({
            "memberId": m.id, "name": m.name, "role": m.role,
            "rentSharePct": m.rent_share_pct, "net": net,
        })
    return sorted(rows, key=lambda r: r["net"])
