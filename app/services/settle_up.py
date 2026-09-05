"""Settle up — "the fastest way for everyone to get square."

`preview()` runs the debt simplifier over the live derived balances (no writes).
`close()` snapshots those transfers as a SettleRun + proposed SettleTxns and pings each
debtor. Marking a transfer paid records a real Payment (the balance source of truth) and
flips the txn to 'paid' — the next balance read reflects it automatically.

A transfer can be paid in instalments: `mark_txn_paid` takes an optional `amount`, writes
a Payment for exactly that much, and leaves the txn 'proposed' with the remainder still
showing until it's covered. Balances need no special case — they already fold over
whatever Payment rows exist.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError, NotFound, Unprocessable
from app.domain import permissions
from app.domain.enums import Permission
from app.domain.settle import simplify
from app.repositories import expenses as expenses_repo
from app.repositories import members as members_repo
from app.services import balances, notifications


async def preview(session: AsyncSession) -> dict:
    # Display the full nets, but SIMPLIFY over the peer-to-peer graph only — that
    # component is provably zero-sum, so simplify()'s precondition always holds (no more
    # HTTP 500 when there are outstanding fines / ledger advances / house payments; those
    # aren't member↔member and are settled elsewhere).
    display = await balances.all_balances(session)
    names = {r["memberId"]: r["name"] for r in display}
    peer = balances.balances_map(await balances.settle_balances(session))
    transfers = [
        {"fromId": f, "fromName": names.get(f), "toId": t, "toName": names.get(t), "amount": a}
        for f, t, a in (simplify(peer) if peer else [])
    ]
    return {"transfers": transfers, "balances": display}


async def close(session: AsyncSession, *, actor, note: Optional[str] = None) -> dict:
    permissions.require(actor, Permission.SETTLE)
    p = await preview(session)
    if not p["transfers"]:
        raise DomainError("Everyone's already square — nothing to settle.")
    run = await expenses_repo.insert_settle_run(session, created_by=actor.id, note=note)
    transfers = []
    for t in p["transfers"]:
        txn = await expenses_repo.insert_settle_txn(
            session, settle_run_id=run.id, from_id=t["fromId"], to_id=t["toId"], amount=t["amount"]
        )
        # The txn id is what /settle/txn/{id}/paid addresses — without it the caller has
        # no handle on the row it just created.
        transfers.append({**t, "txnId": txn.id, "paidAmount": 0, "remaining": txn.amount,
                          "status": txn.status})
    active = {m.id: m for m in await members_repo.list_active(session)}
    for t in p["transfers"]:
        debtor = active.get(t["fromId"])
        if debtor is not None:
            await notifications.settle_proposed(session, debtor=debtor, to_name=t["toName"], amount=t["amount"])
    return {"settleRunId": run.id, "transfers": transfers, "balances": p["balances"]}


async def open_txns(session: AsyncSession) -> dict:
    """The persisted worklist — still-open transfers with what's left on each."""
    rows = await expenses_repo.list_open_txns(session)
    return {
        "transfers": [
            {
                "txnId": r.id,
                "fromId": r.from_id, "fromName": r.from_name,
                "toId": r.to_id, "toName": r.to_name,
                "amount": r.amount,
                "paidAmount": r.paid_amount,
                "remaining": r.amount - r.paid_amount,
                "status": r.status,
            }
            for r in rows
        ]
    }


async def mark_txn_paid(
    session: AsyncSession, *, actor, txn_id: int, amount: Optional[int] = None
) -> dict:
    """Record that a proposed transfer actually happened — writes a Payment against it.

    `amount` omitted pays off whatever is still outstanding (the old all-or-nothing
    behaviour). A smaller `amount` is a part payment: the Payment is written for exactly
    that much, `paid_amount` accumulates, and the txn stays 'proposed' with the remainder
    on the worklist. It only flips to 'paid' once the full amount is covered.
    """
    permissions.require(actor, Permission.SETTLE)
    txn = await expenses_repo.get_settle_txn(session, txn_id)
    if txn is None:
        raise NotFound("No such transfer.")
    if txn.status != "proposed":
        raise DomainError("That transfer is already settled or cancelled.")

    remaining = txn.amount - txn.paid_amount
    paying = remaining if amount is None else amount
    if paying <= 0:
        raise Unprocessable("Amount must be positive.")
    if paying > remaining:
        raise DomainError(f"That's more than the ₹{remaining:,} still outstanding on this transfer.")

    partial = paying < remaining
    pay = await expenses_repo.insert_payment(
        session, from_id=txn.from_id, to_id=txn.to_id, amount=paying, method="upi",
        note="settle-up (part payment)" if partial else "settle-up",
        created_by=actor.id, settle_run_id=txn.settle_run_id,
    )
    txn.paid_amount += paying
    left = txn.amount - txn.paid_amount
    if left == 0:
        txn.status = "paid"
        txn.payment_id = pay.id  # the payment that finally cleared it
    return {
        "ok": True, "paymentId": pay.id, "amount": paying,
        "paidAmount": txn.paid_amount, "remaining": left, "status": txn.status,
    }


async def cancel_txn(session: AsyncSession, *, actor, txn_id: int) -> dict:
    """Cancel a still-proposed transfer — e.g. the debt was cleared directly via /payments,
    so this line would otherwise sit 'proposed' forever. No Payment is written."""
    permissions.require(actor, Permission.SETTLE)
    txn = await expenses_repo.get_settle_txn(session, txn_id)
    if txn is None:
        raise NotFound("No such transfer.")
    if txn.status != "proposed":
        raise DomainError("Only a proposed transfer can be cancelled.")
    txn.status = "cancelled"
    return {"ok": True}
