"""Rent smoke test — rent is a shared expense: one tenant fronts it, the others owe
their rent-share, and it nets into settle-up like any other expense.

    .venv/bin/python3 tests/smoke_rent.py
"""

import asyncio
import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_PATH"] = os.path.join(tempfile.gettempdir(), f"hive_rent_{uuid.uuid4().hex}.db")
os.environ["MONTHLY_RENT"] = "58000"

from app.core.errors import DomainError, Unprocessable  # noqa: E402
from app.db.session import create_all, dispose, session_scope  # noqa: E402
from app.domain.settle import simplify  # noqa: E402
from app.domain.time import add_months, latest_local_month  # noqa: E402
from app.repositories import expenses as expenses_repo  # noqa: E402
from app.repositories import members as members_repo  # noqa: E402
from app.services import balances, members as members_svc, rent  # noqa: E402


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
        async with session_scope() as s:
            await members_svc.set_rent_shares(s, actor=a, shares={a.id: 27, b.id: 27, c.id: 27, d.id: 19})

        # --- per-tenant targets from 27/27/27/19 of ₹58,000 (unchanged) ---
        async with session_scope() as s:
            st = await rent.rent_status(s, "2026-07")
        tgt = {p["name"]: p["target"] for p in st["perTenant"]}
        assert tgt == {"A": 15660, "B": 15660, "C": 15660, "D": 11020}
        assert st["target"] == 58000 and st["collected"] == 0 and st["remaining"] == 58000 and not st["complete"]
        print("ok rent status: per-tenant targets 15660/15660/15660/11020, target ₹58,000")

        # --- A fronts the whole month's rent -> recorded as a shared rent expense ---
        async with session_scope() as s:
            r = await rent.record_rent_payment(s, actor=a, member_id=a.id, amount=58000, month="2026-07")
        assert r["collected"] == 58000 and r["remaining"] == 0 and r["complete"]

        # progress bar still shows the month covered, and *who* fronted it
        async with session_scope() as s:
            st = await rent.rent_status(s, "2026-07")
        assert st["collected"] == 58000 and st["complete"]
        paid = {p["name"]: p["paid"] for p in st["perTenant"]}
        assert paid == {"A": 58000, "B": 0, "C": 0, "D": 0}
        print("ok rent: A fronts ₹58,000 -> month complete, board shows A paid it")

        # --- THE FIX: rent now nets into the settle graph (A credited, others owe shares) ---
        na = await net(a.id)
        assert na["expensesPaid"] == 58000 and na["expenseShare"] == 15660 and na["net"] == 42340
        assert (await net(b.id))["net"] == -15660 and (await net(d.id))["net"] == -11020
        print("ok rent: A owed +42,340; B/C owe 15,660, D owes 11,020 (fronter credited)")

        # --- household still sums to zero; simplifier squares it in 3 transfers to A ---
        async with session_scope() as s:
            rows = await balances.all_balances(s)
        bmap = balances.balances_map(rows)
        assert sum(bmap.values()) == 0
        txns = simplify(bmap)
        assert len(txns) == 3 and {t[1] for t in txns} == {a.id}  # everything flows to A
        print("ok rent: balances sum to 0, settle-up squares it in 3 transfers to A")

        # --- over-target fronting rejected with the exact delta ---
        async with session_scope() as s:
            try:
                await rent.record_rent_payment(s, actor=b, member_id=b.id, amount=1, month="2026-07")
                assert False
            except DomainError as e:
                assert "over" in str(e).lower()
        print("ok rent: fronting past the ₹58,000 target rejected with the delta")

        # --- a tenant repaying their share settles them and lowers A's credit ---
        async with session_scope() as s:
            await expenses_repo.insert_payment(s, from_id=b.id, to_id=a.id, amount=15660, method="upi", created_by=b.id)
        assert (await net(b.id))["net"] == 0
        assert (await net(a.id))["net"] == 42340 - 15660
        print("ok rent: B repays 15,660 -> B square, A's credit drops")

        # --- months are independent ---
        async with session_scope() as s:
            st_aug = await rent.rent_status(s, "2026-08")
        assert st_aug["collected"] == 0 and st_aug["remaining"] == 58000
        print("ok rent: months are independent")

        # --- which month: a past month can be cleared, one month ahead is allowed ---
        async with session_scope() as s:
            await rent.record_rent_payment(s, actor=a, member_id=a.id, amount=20000, month="2026-08")
        async with session_scope() as s:
            r = await rent.record_rent_payment(s, actor=b, member_id=b.id, amount=38000, month="2026-08")
        assert r["complete"] and r["remaining"] == 0
        print("ok rent: a past month's remainder can be paid off in full")

        nxt = add_months(latest_local_month(), 1)
        async with session_scope() as s:
            r = await rent.record_rent_payment(s, actor=a, member_id=a.id, amount=1000, month=nxt)
        assert r["collected"] == 1000
        for bad in (add_months(nxt, 1), "2026-13", "26-07x"):
            async with session_scope() as s:
                try:
                    await rent.record_rent_payment(s, actor=a, member_id=a.id, amount=1, month=bad)
                    assert False, bad
                except Unprocessable:
                    pass
        print("ok rent: next month accepted; further ahead / malformed months rejected")

        print("\nRENT SMOKE: ALL CHECKS PASSED")
    finally:
        await dispose()


if __name__ == "__main__":
    asyncio.run(main())
