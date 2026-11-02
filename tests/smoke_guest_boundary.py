"""Guest money boundary smoke test — a guest can be fined (and owe that fine), and that is
the ONLY money they touch: never a payer, participant or payee of shared costs.

    .venv/bin/python3 tests/smoke_guest_boundary.py
"""

import asyncio
import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_PATH"] = os.path.join(tempfile.gettempdir(), f"hive_guest_{uuid.uuid4().hex}.db")

from app.core.errors import Unprocessable  # noqa: E402
from app.db.session import create_all, dispose, session_scope  # noqa: E402
from app.repositories import expenses as expenses_repo  # noqa: E402
from app.repositories import members as members_repo  # noqa: E402
from app.services import balances, complaints, expenses, ledger, recurring  # noqa: E402

PROOF = [{"source": "upload", "ref": "photo.jpg", "content_type": "image/jpeg"}]


async def add(name, role="tenant"):
    async with session_scope() as s:
        return await members_repo.add(s, name=name, role=role)


async def rejected(fn):
    try:
        async with session_scope() as s:
            await fn(s)
    except Unprocessable:
        return True
    return False


async def main():
    await create_all()
    try:
        a, b = await add("A"), await add("B")
        g = await add("G", role="guest")

        # --- expenses: a guest can't be split in, nor front one ---
        def exp(payer, parts):
            return lambda s: expenses.create_expense(
                s, actor=a, payer_id=payer, amount=900, category="groceries", description=None,
                strategy="equal", params=None, participant_ids=parts, incurred_on="2026-11-01",
            )
        assert await rejected(exp(a.id, [a.id, b.id, g.id]))
        assert await rejected(exp(g.id, [a.id, b.id]))
        async with session_scope() as s:
            eid = await exp(a.id, [a.id, b.id])(s)
        print("ok expense: guest refused as participant and as payer; tenants-only split works")

        # --- editing can't sneak a guest in either ---
        assert await rejected(lambda s: expenses.edit_expense(
            s, actor=a, expense_id=eid, amount=900, category="groceries", description=None,
            strategy="equal", params=None, participant_ids=[a.id, g.id],
        ))
        print("ok edit: guest refused")

        # --- member transfers: no guest on either side ---
        assert await rejected(lambda s: expenses.record_payment(s, actor=a, from_id=g.id, to_id=a.id, amount=100))
        assert await rejected(lambda s: expenses.record_payment(s, actor=a, from_id=a.id, to_id=g.id, amount=100))
        print("ok payment: guest refused as payer and payee")

        # --- recurring templates ---
        def tpl(payer, parts):
            return lambda s: recurring.create_template(
                s, actor=a, name="Wifi", category="internet", amount=1000,
                default_payer_id=payer, strategy="equal", params=None, participant_ids=parts,
            )
        assert await rejected(tpl(a.id, [a.id, g.id]))
        assert await rejected(tpl(g.id, [a.id, b.id]))
        print("ok template: guest refused as participant and default payer")

        # --- ledger credits ---
        assert await rejected(lambda s: ledger.add_credit(
            s, actor=a, member_id=g.id, type="advance", amount=500, reason="x"
        ))
        print("ok ledger: guest can't be credited")

        # --- the balances board is the cost-sharing circle: no guests ---
        async with session_scope() as s:
            board = await balances.all_balances(s)
        assert {r["memberId"] for r in board} == {a.id, b.id}
        print("ok board: tenants only")

        # --- ...but a guest CAN still be fined, and owes it ---
        async with session_scope() as s:
            fid = await complaints.create(s, accused_id=g.id, added_by=a.id, amount=200, proofs=PROOF)
        async with session_scope() as s:
            assert await complaints.accept(s, fid, by_member=g.id)
        async with session_scope() as s:
            gm = await members_repo.get(s, g.id)
            assert (await balances.net_for(s, gm))["finesOwed"] == 200
        print("ok fines: guest fined ₹200 and owes it")

        # --- a tenant demoted to guest pauses their recurring instead of billing them ---
        c = await add("C")
        async with session_scope() as s:
            tid = await tpl(a.id, [a.id, b.id, c.id])(s)
            rid = await recurring.create_recurring(s, actor=a, template_id=tid, day_of_month=1)
        async with session_scope() as s:
            (await members_repo.get(s, c.id)).role = "guest"
        async with session_scope() as s:
            assert await recurring.sweep_due(s) == []
        async with session_scope() as s:
            assert rid not in {r.id for r in await expenses_repo.active_recurrings(s)}
        print("ok recurring: demoted participant pauses the template (no guest billed)")

        print("\nALL GUEST-BOUNDARY CHECKS PASSED")
    finally:
        await dispose()


if __name__ == "__main__":
    asyncio.run(main())
