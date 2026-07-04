"""Settle up — "the fastest way for everyone to get square."

`preview()` runs the debt simplifier over the live derived balances (no writes).
`close()` snapshots those transfers as a SettleRun + proposed SettleTxns and pings each
debtor. Marking a transfer paid records a real Payment (the balance source of truth) and
flips the txn to 'paid' — the next balance read reflects it automatically.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError, NotFound
from app.domain.settle import simplify
from app.repositories import expenses as expenses_repo
from app.repositories import members as members_repo
from app.services import balances, notifications


async def preview(session: AsyncSession) -> dict:
    rows = await balances.all_balances(session)
    names = {r["memberId"]: r["name"] for r in rows}
    bmap = balances.balances_map(rows)
    transfers = [
        {"fromId": f, "fromName": names.get(f), "toId": t, "toName": names.get(t), "amount": a}
        for f, t, a in (simplify(bmap) if bmap else [])
    ]
    return {"transfers": transfers, "balances": rows}


async def close(session: AsyncSession, *, actor, note: Optional[str] = None) -> dict:
    p = await preview(session)
    if not p["transfers"]:
        raise DomainError("Everyone's already square — nothing to settle.")
    run = await expenses_repo.insert_settle_run(session, created_by=actor.id, note=note)
    for t in p["transfers"]:
        await expenses_repo.insert_settle_txn(
            session, settle_run_id=run.id, from_id=t["fromId"], to_id=t["toId"], amount=t["amount"]
        )
    active = {m.id: m for m in await members_repo.list_active(session)}
    for t in p["transfers"]:
        debtor = active.get(t["fromId"])
        if debtor is not None:
            await notifications.settle_proposed(session, debtor=debtor, to_name=t["toName"], amount=t["amount"])
    return {"settleRunId": run.id, **p}


async def mark_txn_paid(session: AsyncSession, *, actor, txn_id: int) -> dict:
    """Record that a proposed transfer actually happened — writes a Payment + closes the txn."""
    txn = await expenses_repo.get_settle_txn(session, txn_id)
    if txn is None:
        raise NotFound("No such transfer.")
    if txn.status != "proposed":
        raise DomainError("That transfer is already settled or cancelled.")
    pay = await expenses_repo.insert_payment(
        session, from_id=txn.from_id, to_id=txn.to_id, amount=txn.amount, method="upi",
        note="settle-up", created_by=actor.id, settle_run_id=txn.settle_run_id,
    )
    txn.status = "paid"
    txn.payment_id = pay.id
    return {"ok": True, "paymentId": pay.id}
