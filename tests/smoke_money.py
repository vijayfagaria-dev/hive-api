"""Money-ledger smoke test — rent shares, rent-by-ratio split, ledger charges/credits,
the 2-month settlement (pot->rent->leftover) + the unpaid-fine penalty, and My Money.

    .venv/bin/python3 tests/smoke_money.py
"""

import asyncio
import os
import sys
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_PATH"] = os.path.join(tempfile.gettempdir(), f"hive_money_{uuid.uuid4().hex}.db")
os.environ["MONTHLY_RENT"] = "200"        # small so leftover/penalty are easy to verify
os.environ["PENALTY_RENT_PCT"] = "20"
os.environ["PENALTY_MONTHS"] = "2"

from app.core.errors import DomainError, Unprocessable  # noqa: E402
from app.db.session import create_all, dispose, session_scope  # noqa: E402
from app.domain.enums import FineStatus  # noqa: E402
from app.domain.money import split_by_ratio  # noqa: E402
from app.domain.time import now_iso  # noqa: E402
from app.repositories import bills as bills_repo  # noqa: E402
from app.repositories import fines as fines_repo  # noqa: E402
from app.repositories import ledger as ledger_repo  # noqa: E402
from app.repositories import members as members_repo  # noqa: E402
from app.services import billing, ledger as ledger_svc, members as members_svc, money, settlements  # noqa: E402


async def add(name):
    async with session_scope() as s:
        return await members_repo.add(s, name=name, role="tenant")


async def add_fine(member_id, amount, *, paid):
    async with session_scope() as s:
        f = await fines_repo.insert(
            s, member_id=member_id, rule_id=None, amount=amount, added_by=member_id,
            status=FineStatus.CONFIRMED, ts=now_iso(), confirm_deadline=None,
        )
        f.resolved_at = now_iso()
        f.paid = paid


async def main():
    # --- pure split helper ---
    assert split_by_ratio(40000, [27, 27, 27, 19]) == [10800, 10800, 10800, 7600]
    assert sum(split_by_ratio(1000, [1, 1, 1, 1])) == 1000          # equal, reconciles
    assert split_by_ratio(100, [27, 27, 27, 19]) == [27, 27, 27, 19]
    assert sum(split_by_ratio(80, [27, 27, 27])) == 80              # remainder handed out
    print("ok split_by_ratio: proportional + always reconciles to total")

    await create_all()
    try:
        amit, rohit, priya, tarun = [await add(n) for n in ("Amit", "Rohit", "Priya", "Tarun")]

        # --- rent shares: enforced to total exactly 100 over all active tenants ---
        async with session_scope() as s:
            for bad in ({amit.id: 27, rohit.id: 27, priya.id: 27, tarun.id: 20},   # sums 101
                        {amit.id: 50, rohit.id: 50}):                               # missing members
                try:
                    await members_svc.set_rent_shares(s, actor=amit, shares=bad); assert False
                except Unprocessable:
                    pass
            await members_svc.set_rent_shares(
                s, actor=amit, shares={amit.id: 27, rohit.id: 27, priya.id: 27, tarun.id: 19}
            )
        async with session_scope() as s:
            shares = {m.name: m.rent_share_pct for m in await members_repo.list_active_tenants(s)}
        assert shares == {"Amit": 27, "Rohit": 27, "Priya": 27, "Tarun": 19}
        print("ok rent shares: must total 100 over all tenants; saved 27/27/27/19")

        # --- rent splits by ratio; other bills split equally ---
        ns = [SimpleNamespace(rent_share_pct=p) for p in (27, 27, 27, 19)]
        assert billing._bill_shares("rent", 40000, ns) == [10800, 10800, 10800, 7600]
        assert billing._bill_shares("electricity", 1000, ns) == [250, 250, 250, 250]
        try:
            billing._bill_shares("rent", 40000, [SimpleNamespace(rent_share_pct=None)] * 4); assert False
        except DomainError:
            pass
        # integration: a real rent bill snapshots ratio shares
        async with session_scope() as s:
            bid = await billing.create_bill(s, type="rent", total=40000, month="2026-06", payer=amit)
        async with session_scope() as s:
            rent_shares = sorted(r.share_amount for r in await bills_repo.list_shares(s, bid))
        assert rent_shares == [7600, 10800, 10800, 10800]
        print("ok bills: rent by ratio (10800/10800/10800/7600), others equal")

        # --- ledger: broker by ratio (debits) + an advance credit ---
        async with session_scope() as s:
            await ledger_svc.add_charge(s, actor=amit, type="broker", total=60000, reason="Broker fee", split="ratio")
            await ledger_svc.add_credit(s, actor=amit, member_id=amit.id, type="advance", amount=30000, reason="Advance paid")
        async with session_scope() as s:
            bal = {m.name: await ledger_repo.balance(s, m.id) for m in await members_repo.list_active_tenants(s)}
        # broker: 27%->-16200, 19%->-11400; Amit also +30000 advance
        assert bal["Tarun"] == -11400 and bal["Rohit"] == -16200 and bal["Amit"] == -16200 + 30000
        print("ok ledger: broker split by ratio (debits) + advance credit")

        # --- settlement: pot -> rent -> leftover by ratio, + penalty for a defaulter ---
        await add_fine(rohit.id, 300, paid=True)    # collected into the pot
        await add_fine(tarun.id, 500, paid=False)   # unpaid -> default -> penalty
        async with session_scope() as s:
            pv = await settlements.preview(s)
        assert pv["pot"] == 300 and pv["appliedToRent"] == 200 and pv["leftover"] == 100
        assert sum(p["amount"] for p in pv["payouts"]) == 100                 # leftover fully distributed
        pen = pv["penalties"][0]
        assert pen["defaulterName"] == "Tarun" and pen["amount"] == 80        # 20% of 200 * 2
        assert sum(c["amount"] for c in pen["credits"]) == 80                 # redistributed to the others
        print("ok settlement preview: pot 300 -> rent 200, leftover 100 by ratio; Tarun penalty 80")

        async with session_scope() as s:
            res = await settlements.close(s, actor=amit, note="period 1")
        assert res["settlementId"]
        async with session_scope() as s:
            tarun_bal_after = await ledger_repo.balance(s, tarun.id)
            setts = await ledger_repo.list_settlements(s)
        # Tarun: broker -11400, payout +19, penalty -80  => -11461
        assert tarun_bal_after == -11400 + 19 - 80
        assert len(setts) == 1 and setts[0].pot_collected == 300 and setts[0].leftover == 100
        print("ok settlement close: persisted + ledger entries (Tarun -11461)")

        # closing again with nothing new -> rejected
        async with session_scope() as s:
            try:
                await settlements.close(s, actor=amit); assert False
            except DomainError:
                pass
        print("ok second close rejected (nothing new in the period)")

        # --- My Money unifies fines + bills + ledger ---
        async with session_scope() as s:
            tarun_live = await members_repo.get(s, tarun.id)
            stmt = await money.statement(s, tarun_live)
        assert stmt["finesOwed"] == 500 and stmt["billsOwed"] == 7600  # unpaid fine + rent share
        assert stmt["ledgerBalance"] == -11461
        assert stmt["net"] == -11461 - 500 - 7600 and stmt["owes"] == 19561
        assert any(b["type"] == "rent" and b["amount"] == 7600 for b in stmt["bills"])
        print("ok My Money: net unifies fines + bills + ledger (Tarun owes ₹19,561)")

        print("\nMONEY SMOKE: ALL CHECKS PASSED")
    finally:
        await dispose()


if __name__ == "__main__":
    asyncio.run(main())
