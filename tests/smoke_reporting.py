"""Reporting + settle-up guard smoke test.

    .venv/bin/python3 tests/smoke_reporting.py

Regression coverage for:
  - Bug 6: the "biggest false reporter" (overturn) leaderboard must only list members
    with >=1 *decided* rejection (VOID). A clean reporter (0 overturned) never appears,
    and an in-flight DISPUTED vote is NOT counted as overturned.
  - Settle-up 500->400: when balances don't net to zero (an unpaid fine in the mix),
    settle_up.preview raises a DomainError (400), never a bare ValueError (500).
"""

import asyncio
import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_PATH"] = os.path.join(tempfile.gettempdir(), f"hive_report_{uuid.uuid4().hex}.db")

from app.core.errors import Conflict, DomainError, Unprocessable  # noqa: E402
from app.db.session import create_all, dispose, session_scope  # noqa: E402
from app.domain.enums import FineStatus  # noqa: E402
from app.domain.time import now_iso  # noqa: E402
from app.repositories import fines as fines_repo  # noqa: E402
from app.repositories import members as members_repo  # noqa: E402
from app.services import expenses, reporting, settle_up  # noqa: E402


async def add(name):
    async with session_scope() as s:
        return (await members_repo.add(s, name=name, role="tenant")).id


async def file_fine(accuser, accused, status):
    async with session_scope() as s:
        await fines_repo.insert(
            s, member_id=accused, rule_id=None, amount=50, added_by=accuser,
            status=status, ts=now_iso(), confirm_deadline=None,
        )


async def main():
    await create_all()
    try:
        clean = await add("CleanReporter")     # files complaints that all stick -> 0 overturned
        bad = await add("BadReporter")          # files complaints that get voided -> overturned>0
        pending_only = await add("PendingReporter")  # only in-flight disputed -> NOT overturned
        target = await add("Target")

        # Clean: 2 filed, both upheld/confirmed -> filed=2, overturned=0.
        await file_fine(clean, target, FineStatus.CONFIRMED)
        await file_fine(clean, target, FineStatus.UPHELD)
        # Bad: 4 filed, 2 void (overturned) + 2 confirmed -> filed=4, overturned=2, rate=50%.
        await file_fine(bad, target, FineStatus.VOID)
        await file_fine(bad, target, FineStatus.VOID)
        await file_fine(bad, target, FineStatus.CONFIRMED)
        await file_fine(bad, target, FineStatus.CONFIRMED)
        # PendingReporter: 2 filed, both DISPUTED (a live vote, not a rejection).
        await file_fine(pending_only, target, FineStatus.DISPUTED)
        await file_fine(pending_only, target, FineStatus.DISPUTED)

        async with session_scope() as s:
            board = await reporting.overturn(s)
        by_name = {r["name"]: r for r in board}

        # Only BadReporter qualifies — clean 0% and disputed-only are both excluded.
        assert set(by_name) == {"BadReporter"}, by_name
        assert "CleanReporter" not in by_name   # Bug 6: 0-overturn reporter must not appear
        assert "PendingReporter" not in by_name  # DISPUTED (in-flight) is not a rejection
        b = by_name["BadReporter"]
        assert b["filed"] == 4 and b["overturned"] == 2 and b["overturn_rate"] == 50
        print("ok Bug6: leaderboard lists only reporters with >=1 decided rejection")

        # dashboard() surfaces the same filtered board.
        async with session_scope() as s:
            dash = await reporting.dashboard(s)
        assert {r["name"] for r in dash["overturn"]} == {"BadReporter"}
        print("ok Bug6: dashboard overturn board is filtered too")

        # --- Settle-up settles the PEER graph only; fines/ledger are excluded ---
        async with session_scope() as s:
            await fines_repo.insert(
                s, member_id=target, rule_id=None, amount=200, added_by=bad,
                status=FineStatus.CONFIRMED, ts=now_iso(), confirm_deadline=None,
            )  # an unpaid fine is one-sided (owed to the pot) — NOT a peer debt
        # Previously this made the balance map non-zero and crashed simplify() (HTTP 500).
        # Now fines are excluded from the settle graph, so preview just succeeds with no
        # transfers (there are no shared expenses to settle here).
        async with session_scope() as s:
            pv = await settle_up.preview(s)
        assert pv["transfers"] == []
        print("ok settle-up: fines excluded from the peer graph; preview succeeds (no 500)")

        # --- POST /payments validation (latent high-severity bug) ---
        async with session_scope() as s:
            actor = await members_repo.get(s, bad)
            # self-payment rejected
            try:
                await expenses.record_payment(s, actor=actor, from_id=bad, to_id=bad, amount=100, method="upi")
                assert False
            except DomainError:
                pass
            # unknown payee rejected
            try:
                await expenses.record_payment(s, actor=actor, from_id=bad, to_id=999999, amount=100, method="upi")
                assert False
            except Unprocessable:
                pass
            # a valid transfer records; an immediate identical retry is a dedupe Conflict
            p = await expenses.record_payment(s, actor=actor, from_id=bad, to_id=clean, amount=100, method="upi", note="rent")
            assert p.id
            try:
                await expenses.record_payment(s, actor=actor, from_id=bad, to_id=clean, amount=100, method="upi", note="rent")
                assert False
            except Conflict:
                pass
        print("ok payments validation: self-pay/unknown-payee rejected; double-submit deduped")

        print("\nREPORTING SMOKE: ALL CHECKS PASSED")
    finally:
        await dispose()


if __name__ == "__main__":
    asyncio.run(main())
