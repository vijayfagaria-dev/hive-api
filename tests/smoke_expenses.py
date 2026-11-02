"""Expense engine smoke test — create with the payer credit, derived balances,
payments, and the round-trip against the debt simplifier.

    .venv/bin/python3 tests/smoke_expenses.py
"""

import asyncio
import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_PATH"] = os.path.join(tempfile.gettempdir(), f"hive_exp_{uuid.uuid4().hex}.db")

from app.core.errors import Forbidden, Unprocessable  # noqa: E402
from app.db.session import create_all, dispose, session_scope  # noqa: E402
from app.domain.settle import simplify  # noqa: E402
from app.repositories import expenses as expenses_repo  # noqa: E402
from app.repositories import members as members_repo  # noqa: E402
from app.services import balances, expenses, settle_up  # noqa: E402


async def add(name):
    async with session_scope() as s:
        return await members_repo.add(s, name=name, role="tenant")


async def net(member_id):
    async with session_scope() as s:
        m = await members_repo.get(s, member_id)
        return await balances.net_for(s, m)


async def main():
    await create_all()
    try:
        a, b, c, d = [await add(n) for n in ("A", "B", "C", "D")]
        pids = [a.id, b.id, c.id, d.id]

        # --- A pays ₹58,000 brokerage, ratio 27/27/27/19 ---
        async with session_scope() as s:
            eid = await expenses.create_expense(
                s, actor=a, payer_id=a.id, amount=58000, category="broker", description="Move-in broker",
                strategy="ratio", params={"weights": {a.id: 27, b.id: 27, c.id: 27, d.id: 19}},
                participant_ids=pids, incurred_on="2026-07-01",
            )
        async with session_scope() as s:
            splits = {r.member_name: r.owed_amount for r in await expenses_repo.list_splits(s, eid)}
        assert splits == {"A": 15660, "B": 15660, "C": 15660, "D": 11020}

        # THE PAYER FIX: A is owed 58000-15660 = +42,340, never shown owing their share
        na = await net(a.id)
        assert na["expensesPaid"] == 58000 and na["expenseShare"] == 15660
        assert na["net"] == 42340 and na["owed"] == 42340 and na["owes"] == 0
        assert (await net(b.id))["net"] == -15660 and (await net(d.id))["net"] == -11020
        print("ok expense: A paid 58000 -> A owed +42,340 (payer credited, not charged own share)")

        # --- balances sum to zero + the simplifier settles it in 3 transfers ---
        async with session_scope() as s:
            rows = await balances.all_balances(s)
        bmap = balances.balances_map(rows)
        assert sum(bmap.values()) == 0
        txns = simplify(bmap)
        assert len(txns) == 3 and {t[1] for t in txns} == {a.id}   # all flow to A
        print("ok balances: household sums to 0, settles in 3 transfers to A")

        # --- record a payment: B pays A ₹15,660 -> B settled, A down to +26,680 ---
        async with session_scope() as s:
            await expenses_repo.insert_payment(s, from_id=b.id, to_id=a.id, amount=15660, method="upi", created_by=b.id)
        assert (await net(b.id))["net"] == 0
        assert (await net(a.id))["net"] == 42340 - 15660
        print("ok payment: B->A 15,660 settles B, reduces A's credit")

        # --- an equal split excludes a non-participant; payer credited the full total ---
        d_net_before = (await net(d.id))["net"]
        async with session_scope() as s:
            gid = await expenses.create_expense(
                s, actor=a, payer_id=c.id, amount=300, category="groceries", description=None,
                strategy="equal", params=None, participant_ids=[a.id, b.id, c.id],  # D not included
                incurred_on="2026-07-02",
            )
        async with session_scope() as s:
            gsplits = {r.member_name: r.owed_amount for r in await expenses_repo.list_splits(s, gid)}
        assert gsplits == {"A": 100, "B": 100, "C": 100}          # equal 3-way, D excluded
        assert (await net(c.id))["expensesPaid"] == 300           # C fronted the total
        assert (await net(d.id))["net"] == d_net_before           # D untouched by this expense
        print("ok equal split: 3-way (D excluded, ₹100 each), payer C credited the total")

        # --- validation ---
        async with session_scope() as s:
            for bad in (
                dict(payer_id=a.id, amount=100, category="bogus", strategy="equal", params=None, participant_ids=[a.id]),
                dict(payer_id=a.id, amount=100, category="misc", strategy="equal", params=None, participant_ids=[]),
                dict(payer_id=999, amount=100, category="misc", strategy="equal", params=None, participant_ids=[a.id]),
            ):
                try:
                    await expenses.create_expense(s, actor=a, description=None, incurred_on="2026-07-03", **bad)
                    assert False
                except Unprocessable:
                    pass
        print("ok validation: bad category / no participants / unknown payer rejected")

        # --- settle-up: preview -> close (persist proposed txns) -> mark paid ---
        async with session_scope() as s:
            pv = await settle_up.preview(s)
        # everyone's transfers reconcile the current balances to zero
        assert pv["transfers"], "expected outstanding transfers"
        assert sum(t["amount"] for t in pv["transfers"]) > 0
        async with session_scope() as s:
            res = await settle_up.close(s, actor=a, note="July settle")
        run_id = res["settleRunId"]
        async with session_scope() as s:
            open_txns = await expenses_repo.list_open_txns(s)
        assert open_txns, "close should persist proposed transfers"
        # mark the first proposed transfer paid -> writes a payment, flips status
        txn = open_txns[0]
        before = (await net(txn.from_id))["net"]
        async with session_scope() as s:
            await settle_up.mark_txn_paid(s, actor=a, txn_id=txn.id)
        after = (await net(txn.from_id))["net"]
        assert after == before + txn.amount   # paying raises the payer's net toward 0
        async with session_scope() as s:
            t2 = await expenses_repo.get_settle_txn(s, txn.id)
        assert t2.status == "paid" and t2.payment_id
        # marking it again is rejected
        async with session_scope() as s:
            try:
                await settle_up.mark_txn_paid(s, actor=a, txn_id=txn.id); assert False
            except Exception:
                pass
        print("ok settle-up: preview + close persists transfers; mark-paid records a payment")

        # a still-proposed transfer can be cancelled (e.g. the debt was paid directly), so it
        # no longer sits 'proposed' forever
        async with session_scope() as s:
            remaining = await expenses_repo.list_open_txns(s)
        assert remaining, "expected other proposed transfers"
        async with session_scope() as s:
            await settle_up.cancel_txn(s, actor=a, txn_id=remaining[0].id)
        async with session_scope() as s:
            t3 = await expenses_repo.get_settle_txn(s, remaining[0].id)
        assert t3.status == "cancelled"
        async with session_scope() as s:
            try:
                await settle_up.cancel_txn(s, actor=a, txn_id=remaining[0].id); assert False  # not proposed anymore
            except Exception:
                pass
        print("ok settle-up: a proposed transfer can be cancelled (no longer stuck)")

        # --- edit recomputes splits + balances; delete drops it out entirely ---
        async with session_scope() as s:
            eid2 = await expenses.create_expense(
                s, actor=a, payer_id=d.id, amount=400, category="maintenance", description="cylinder",
                strategy="equal", params=None, participant_ids=[a.id, b.id, c.id, d.id], incurred_on="2026-07-05",
            )
        d_before = (await net(d.id))["net"]
        # edit: raise to ₹800, split among only A & D
        async with session_scope() as s:
            await expenses.edit_expense(
                s, actor=a, expense_id=eid2, amount=800, category="maintenance", description="cylinder x2",
                strategy="equal", params=None, participant_ids=[a.id, d.id],
            )
        async with session_scope() as s:
            esplits = {r.member_name: r.owed_amount for r in await expenses_repo.list_splits(s, eid2)}
        assert esplits == {"A": 400, "D": 400}   # re-snapshotted; B & C removed
        # this expense's contribution to D changed from (paid 400 − owed 100)=+300 to (800 − 400)=+400
        assert (await net(d.id))["net"] == d_before - 300 + 400
        # delete: only the payer (D) may — A's attempt is refused and changes nothing
        d_pre_del = (await net(d.id))["net"]
        async with session_scope() as s:
            try:
                await expenses.void_expense(s, actor=a, expense_id=eid2); assert False
            except Forbidden:
                pass
        assert (await net(d.id))["net"] == d_pre_del
        # the payer deletes it: the expense leaves every balance
        async with session_scope() as s:
            await expenses.void_expense(s, actor=d, expense_id=eid2)
        assert (await net(d.id))["net"] == d_pre_del - (800 - 400)   # its +400 contribution removed
        # a deleted expense is out of the feed too (matches balances), but still available
        # for an explicit history view
        async with session_scope() as s:
            listed = [r.id for r in await expenses_repo.list_expenses(s)]
            listed_all = [r.id for r in await expenses_repo.list_expenses(s, include_void=True)]
        assert eid2 not in listed and eid2 in listed_all
        async with session_scope() as s:
            try:
                await expenses.void_expense(s, actor=d, expense_id=eid2); assert False   # already void
            except Exception:
                pass
        print("ok edit/delete: re-splits + rebalances; delete voids it out of balances AND the feed")

        print("\nEXPENSES SMOKE: ALL CHECKS PASSED")
    finally:
        await dispose()


if __name__ == "__main__":
    asyncio.run(main())
