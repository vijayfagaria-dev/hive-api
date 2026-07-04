"""Templates + recurring generation smoke test — prefill + idempotent monthly sweep.

    .venv/bin/python3 tests/smoke_recurring.py
"""

import asyncio
import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_PATH"] = os.path.join(tempfile.gettempdir(), f"hive_rec_{uuid.uuid4().hex}.db")

from app.db.session import create_all, dispose, session_scope  # noqa: E402
from app.domain.time import now_iso  # noqa: E402
from app.repositories import expenses as expenses_repo  # noqa: E402
from app.repositories import members as members_repo  # noqa: E402
from app.repositories import notifications as notifications_repo  # noqa: E402
from app.services import balances, recurring  # noqa: E402


async def add(name):
    async with session_scope() as s:
        return await members_repo.add(s, name=name, role="tenant")


async def main():
    await create_all()
    try:
        a, b, c, d = [await add(n) for n in ("A", "B", "C", "D")]
        pids = [a.id, b.id, c.id, d.id]
        month = now_iso()[:7]

        # --- template: internet ₹1,200, equal, A pays ---
        async with session_scope() as s:
            tid = await recurring.create_template(
                s, actor=a, name="Internet", category="internet", amount=1200,
                default_payer_id=a.id, strategy="equal", params=None, participant_ids=pids,
            )
        async with session_scope() as s:
            pf = await recurring.prefill(s, tid, "2026-08")
        assert pf["amount"] == 1200 and pf["payerId"] == a.id and pf["participantIds"] == pids
        assert pf["incurredOn"] == "2026-08-01" and "Internet" in pf["description"]
        print("ok template + prefill: editable draft for a chosen month")

        # --- recurring on the 5th ---
        async with session_scope() as s:
            rid = await recurring.create_recurring(s, actor=a, template_id=tid, day_of_month=5)

        # --- sweep generates this month's expense once ---
        async with session_scope() as s:
            made = await recurring.sweep_due(s)
        assert len(made) == 1
        async with session_scope() as s:
            splits = {r.member_name: r.owed_amount for r in await expenses_repo.list_splits(s, made[0])}
        assert splits == {"A": 300, "B": 300, "C": 300, "D": 300}  # 1200 / 4
        # A paid 1200, owes 300 -> +900 credit
        async with session_scope() as s:
            na = await balances.net_for(s, await members_repo.get(s, a.id))
        assert na["net"] == 900 and na["expensesPaid"] == 1200
        print("ok recurring sweep: generated internet expense, A credited +900")

        # --- idempotent: re-running the sweep the same month generates nothing ---
        async with session_scope() as s:
            again = await recurring.sweep_due(s)
        assert again == []
        async with session_scope() as s:
            assert await expenses_repo.recurring_generated(s, rid, month) is True
        print("ok recurring sweep: idempotent — no duplicate for the same month")

        # --- a template whose split becomes invalid PAUSES loudly (not silently skipped) ---
        async with session_scope() as s:
            tid2 = await recurring.create_template(
                s, actor=a, name="Cleaner", category="maintenance", amount=1000,
                default_payer_id=a.id, strategy="percentage",
                params={"pct": {a.id: 25, b.id: 25, c.id: 25, d.id: 25}}, participant_ids=pids,
            )
            rid2 = await recurring.create_recurring(s, actor=a, template_id=tid2, day_of_month=6)
        # config drift: the percentages now total 90 (invalid) — generation will fail
        async with session_scope() as s:
            t = await expenses_repo.get_template(s, tid2)
            t.split_params = {"pct": {a.id: 25, b.id: 25, c.id: 20, d.id: 20}}
        async with session_scope() as s:
            made2 = await recurring.sweep_due(s)
        assert made2 == []  # broken one didn't generate; the internet one is already done this month
        async with session_scope() as s:
            status = {r.id: r.status for r in await expenses_repo.list_recurring(s)}
        assert status[rid2] == "paused"   # broken recurring paused (no retry-spam every sweep)
        assert status[rid] == "active"    # the healthy one is untouched
        async with session_scope() as s:
            kinds = [n.kind for n in await notifications_repo.list_for(s, a.id)]
        assert "recurring_failed" in kinds  # the flat was notified loudly, not silently skipped
        print("ok recurring: a broken template pauses + notifies (never silently swallowed)")

        print("\nRECURRING SMOKE: ALL CHECKS PASSED")
    finally:
        await dispose()


if __name__ == "__main__":
    asyncio.run(main())
