"""Rent-as-landlord smoke test — ₹58,000 monthly validation + per-tenant targets.

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

from app.core.errors import DomainError  # noqa: E402
from app.db.session import create_all, dispose, session_scope  # noqa: E402
from app.repositories import members as members_repo  # noqa: E402
from app.services import balances, members as members_svc, rent  # noqa: E402


async def add(name):
    async with session_scope() as s:
        return await members_repo.add(s, name=name, role="tenant")


async def main():
    await create_all()
    try:
        a, b, c, d = [await add(n) for n in ("A", "B", "C", "D")]
        async with session_scope() as s:
            await members_svc.set_rent_shares(s, actor=a, shares={a.id: 27, b.id: 27, c.id: 27, d.id: 19})

        # --- per-tenant targets from 27/27/27/19 of ₹58,000 ---
        async with session_scope() as s:
            st = await rent.rent_status(s, "2026-07")
        tgt = {p["name"]: p["target"] for p in st["perTenant"]}
        assert tgt == {"A": 15660, "B": 15660, "C": 15660, "D": 11020}
        assert st["target"] == 58000 and st["collected"] == 0 and st["remaining"] == 58000 and not st["complete"]
        print("ok rent status: per-tenant targets 15660/15660/15660/11020, target ₹58,000")

        # --- partial payments accumulate; under-target allowed ---
        async with session_scope() as s:
            r = await rent.record_rent_payment(s, actor=a, member_id=a.id, amount=15660, month="2026-07")
        assert r["collected"] == 15660 and r["remaining"] == 42340 and not r["complete"]
        async with session_scope() as s:
            for m in (b, c):
                await rent.record_rent_payment(s, actor=m, member_id=m.id, amount=15660, month="2026-07")
        print("ok rent: partial payments accumulate (under-target allowed)")

        # --- over-payment rejected with the exact delta ---
        async with session_scope() as s:
            try:
                await rent.record_rent_payment(s, actor=d, member_id=d.id, amount=20000, month="2026-07")  # 46980+20000 > 58000
                assert False
            except DomainError as e:
                assert "over" in str(e).lower()
        print("ok rent: over-target payment rejected with the delta")

        # --- exact completion fires 'complete' ---
        async with session_scope() as s:
            r = await rent.record_rent_payment(s, actor=d, member_id=d.id, amount=11020, month="2026-07")
        assert r["collected"] == 58000 and r["remaining"] == 0 and r["complete"]
        print("ok rent: reaching ₹58,000 exactly marks the month complete")

        # --- rent is landlord-facing: it does NOT touch member↔member balances ---
        async with session_scope() as s:
            na = await balances.net_for(s, await members_repo.get(s, a.id))
        assert na["net"] == 0 and na["sent"] == 0  # rent payment to house excluded from 'sent'
        print("ok rent: payments to the house stay out of the settle-up balances")

        # --- a different month is independent ---
        async with session_scope() as s:
            st_aug = await rent.rent_status(s, "2026-08")
        assert st_aug["collected"] == 0 and st_aug["remaining"] == 58000
        print("ok rent: months are independent")

        print("\nRENT SMOKE: ALL CHECKS PASSED")
    finally:
        await dispose()


if __name__ == "__main__":
    asyncio.run(main())
