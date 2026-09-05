"""Partial settle-up payments — pay part of a proposed transfer now, the rest later.

    .venv/bin/python3 tests/smoke_partial_settle.py
"""

import asyncio
import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_PATH"] = os.path.join(tempfile.gettempdir(), f"hive_part_{uuid.uuid4().hex}.db")

from app.core.errors import DomainError, Unprocessable  # noqa: E402
from app.db.session import create_all, dispose, session_scope  # noqa: E402
from app.repositories import expenses as expenses_repo  # noqa: E402
from app.repositories import members as members_repo  # noqa: E402
from app.services import balances, expenses, settle_up  # noqa: E402


async def add(name):
    async with session_scope() as s:
        return await members_repo.add(s, name=name, role="tenant")


async def net(member_id):
    async with session_scope() as s:
        m = await members_repo.get(s, member_id)
        return (await balances.net_for(s, m))["net"]


async def txn_state(txn_id):
    async with session_scope() as s:
        t = await expenses_repo.get_settle_txn(s, txn_id)
        return t.amount, t.paid_amount, t.status, t.payment_id


async def main():
    await create_all()
    try:
        a, b = await add("A"), await add("B")

        # A fronts ₹1,000 split equally -> B owes A ₹500
        async with session_scope() as s:
            await expenses.create_expense(
                s, actor=a, payer_id=a.id, amount=1000, category="groceries", description="Big shop",
                strategy="equal", params=None, participant_ids=[a.id, b.id], incurred_on="2026-09-01",
            )
        assert await net(b.id) == -500, await net(b.id)

        # close() must hand back the txn ids — without them the client can't address a transfer
        async with session_scope() as s:
            res = await settle_up.close(s, actor=a, note="Sept")
        assert len(res["transfers"]) == 1
        t = res["transfers"][0]
        assert t["txnId"] and t["amount"] == 500 and t["remaining"] == 500 and t["paidAmount"] == 0
        txn_id = t["txnId"]
        print("ok close: returns txnId + remaining (the transfer is now addressable)")

        # --- part payment 1: B pays ₹200 of the ₹500 ---
        async with session_scope() as s:
            r = await settle_up.mark_txn_paid(s, actor=a, txn_id=txn_id, amount=200)
        assert r["amount"] == 200 and r["paidAmount"] == 200 and r["remaining"] == 300
        assert r["status"] == "proposed", "a part-paid transfer must stay open"
        assert await net(b.id) == -300, "balance must reflect the ₹200 immediately"
        assert await txn_state(txn_id) == (500, 200, "proposed", None)
        print("ok part payment: ₹200 of ₹500 -> ₹300 left, txn still open, balance moved")

        # it stays on the worklist, showing what's left
        async with session_scope() as s:
            worklist = await settle_up.open_txns(s)
        assert len(worklist["transfers"]) == 1
        assert worklist["transfers"][0]["remaining"] == 300
        print("ok worklist: part-paid transfer still listed with ₹300 remaining")

        # --- overpaying the remainder is rejected ---
        async with session_scope() as s:
            try:
                await settle_up.mark_txn_paid(s, actor=a, txn_id=txn_id, amount=301)
                assert False, "overpay should be rejected"
            except DomainError:
                pass
            try:
                await settle_up.mark_txn_paid(s, actor=a, txn_id=txn_id, amount=0)
                assert False, "zero should be rejected"
            except (Unprocessable, DomainError):
                pass
        assert await txn_state(txn_id) == (500, 200, "proposed", None), "rejects must not mutate"
        print("ok validation: can't pay more than what's left, or a non-positive amount")

        # --- part payment 2: another ₹100, still open ---
        async with session_scope() as s:
            r = await settle_up.mark_txn_paid(s, actor=a, txn_id=txn_id, amount=100)
        assert r["remaining"] == 200 and r["status"] == "proposed"
        print("ok part payment: instalments accumulate (₹300 paid, ₹200 left)")

        # --- final: omitting the amount clears whatever is outstanding ---
        async with session_scope() as s:
            r = await settle_up.mark_txn_paid(s, actor=a, txn_id=txn_id)
        assert r["amount"] == 200 and r["remaining"] == 0 and r["status"] == "paid"
        amount, paid, status, pay_id = await txn_state(txn_id)
        assert (amount, paid, status) == (500, 500, "paid") and pay_id
        assert await net(b.id) == 0 and await net(a.id) == 0, "everyone square"
        print("ok final payment: no amount = pay the rest -> txn closes, everyone square")

        # --- a closed transfer takes no further payment ---
        async with session_scope() as s:
            try:
                await settle_up.mark_txn_paid(s, actor=a, txn_id=txn_id, amount=50)
                assert False, "a paid transfer must be rejected"
            except DomainError:
                pass
        async with session_scope() as s:
            assert not (await settle_up.open_txns(s))["transfers"]
        print("ok closed: a settled transfer rejects further payment and leaves the worklist")

        # --- the four payments recorded are the real audit trail ---
        async with session_scope() as s:
            rows = await expenses_repo.list_open_txns(s)
        assert not rows
        print("\nPARTIAL SETTLE SMOKE: ALL CHECKS PASSED")
    finally:
        await dispose()


asyncio.run(main())
