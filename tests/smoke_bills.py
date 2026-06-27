"""Bill declare-and-confirm lifecycle smoke test — service + repo.

    .venv/bin/python3 tests/smoke_bills.py

Covers: declare ("I paid") -> pending + share snapshot + claimed notification; dispute
(payer can't, non-payer can, blocks auto-confirm); the sweep auto-confirming overdue
undisputed bills (idempotent) while skipping disputed ones; deadline enforcement.
"""

import asyncio
import datetime as dt
import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_PATH"] = os.path.join(tempfile.gettempdir(), f"hive_bills_{uuid.uuid4().hex}.db")
os.environ["BILL_CONFIRM_HOURS"] = "12"

from app.core.errors import DomainError  # noqa: E402
from app.db.session import create_all, dispose, session_scope  # noqa: E402
from app.domain.enums import BillStatus  # noqa: E402
from app.repositories import bills as bills_repo  # noqa: E402
from app.repositories import members as members_repo  # noqa: E402
from app.repositories import notifications as notifications_repo  # noqa: E402
from app.services import billing  # noqa: E402


def _past() -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


async def add(name):
    async with session_scope() as s:
        return await members_repo.add(s, name=name, role="tenant")


async def create(payer, type="electricity", total=900, month="2026-06"):
    async with session_scope() as s:
        return await billing.create_bill(s, type=type, total=total, month=month, payer=payer)


async def get(bid):
    async with session_scope() as s:
        return await bills_repo.get_bill(s, bid)


async def dispute(bid, member, reason=None):
    async with session_scope() as s:
        await billing.dispute_bill(s, bill_id=bid, member=member, reason=reason)


async def set_deadline_past(bid):
    async with session_scope() as s:
        b = await bills_repo.get_bill(s, bid)
        b.confirm_deadline = _past()


async def sweep():
    async with session_scope() as s:
        return await billing.sweep_due(s)


async def notif_kinds(mid):
    async with session_scope() as s:
        return [n.kind for n in await notifications_repo.list_for(s, mid)]


async def event_types(bid):
    from sqlalchemy import select

    from app.db.models import BillEvent
    async with session_scope() as s:
        return [r.type for r in await s.scalars(select(BillEvent).where(BillEvent.bill_id == bid))]


async def main():
    await create_all()
    try:
        amit = await add("Amit")
        rohit = await add("Rohit")
        priya = await add("Priya")

        # --- declare: pending + snapshot + claimed notification ----------------
        b1 = await create(amit, total=900)
        bill = await get(b1)
        assert bill.status == BillStatus.PENDING and bill.paid_by == amit.id and bill.confirm_deadline
        async with session_scope() as s:
            shares = await bills_repo.list_shares(s, b1)
        assert len(shares) == 3 and sum(r.share_amount for r in shares) == 900
        assert "created" in await event_types(b1)
        assert "bill_claimed" in await notif_kinds(rohit.id) and "bill_claimed" in await notif_kinds(priya.id)
        assert "bill_claimed" not in await notif_kinds(amit.id)  # payer isn't pinged
        print("ok declare -> pending + 3-way snapshot + others notified")

        # --- dispute rules -----------------------------------------------------
        try:
            await dispute(b1, amit); assert False           # payer can't dispute own
        except DomainError:
            pass
        await dispute(b1, rohit, reason="I paid this one")
        bill = await get(b1)
        assert bill.status == BillStatus.DISPUTED and bill.disputed_by == rohit.id
        assert bill.dispute_reason == "I paid this one" and "disputed" in await event_types(b1)
        assert "bill_disputed" in await notif_kinds(amit.id)  # payer told
        try:
            await dispute(b1, priya); assert False           # already disputed -> not pending
        except DomainError:
            pass
        print("ok dispute: payer blocked, non-payer disputes, re-dispute blocked, payer notified")

        # --- sweep: auto-confirm overdue undisputed; skip disputed ------------
        b2 = await create(amit, type="water", total=300)
        await set_deadline_past(b2)
        await set_deadline_past(b1)   # disputed — must NOT be swept
        confirmed = await sweep()
        assert b2 in confirmed and b1 not in confirmed
        assert (await get(b2)).status == BillStatus.CONFIRMED
        assert (await get(b2)).resolved_at and "auto_confirmed" in await event_types(b2)
        assert (await get(b1)).status == BillStatus.DISPUTED  # untouched
        assert "bill_auto_confirmed" in await notif_kinds(priya.id)
        assert await sweep() == []    # idempotent — nothing left pending+overdue
        print("ok sweep auto-confirms overdue, skips disputed, idempotent")

        # --- deadline enforcement ---------------------------------------------
        b3 = await create(amit, type="rent", total=500)
        await set_deadline_past(b3)
        try:
            await dispute(b3, rohit); assert False           # window closed
        except DomainError:
            pass
        print("ok dispute blocked after the window closes")

        print("\nBILLS SMOKE: ALL CHECKS PASSED")
    finally:
        await dispose()


if __name__ == "__main__":
    asyncio.run(main())
