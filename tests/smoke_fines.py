"""Phase 2 smoke test — the fine lifecycle (app/fines.py).

Standalone, no pytest needed — runs against a throwaway temp SQLite DB:

    .venv/Scripts/python.exe tests/smoke_fines.py

Exits non-zero on the first failed assertion. Covers every fines business rule
(BR-021/030..037) plus the fixes from the Phase 2 review gate (single-clock
deadline, mark_paid guard + bool return, sweep RETURNING, is_active guard).
"""

import asyncio
import datetime as dt
import os
import sys
import tempfile
import uuid
from pathlib import Path

# Allow `python tests/smoke_fines.py` from anywhere — put the repo root on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["DATABASE_PATH"] = os.path.join(tempfile.gettempdir(), f"hive_smoke_{uuid.uuid4().hex}.db")
os.environ["COOLING_HOURS"] = "12"

from app import db as dbm, fines, queries  # noqa: E402  (after env is set)


def _past(hours: int = 1) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


async def main() -> None:
    db = await dbm.connect()
    try:
        amit = await queries.add_member(db, "Amit")
        rohit = await queries.add_member(db, "Rohit")
        rule = await queries.add_rule(db, "kitchen", "Left dishes", 50, is_favorite=True)

        # BR-034 — accuser and accused must differ.
        try:
            await fines.create_fine(db, accused_id=amit, added_by=amit, rule_id=rule)
            assert False, "self-fine should raise"
        except fines.FineError:
            pass
        print("ok BR-034 self-fine rejected")

        # BR-031 — pending fine; confirm_deadline == ts + COOLING_HOURS exactly (single clock read).
        fid = await fines.create_fine(db, accused_id=rohit, added_by=amit, rule_id=rule)
        f = await queries.get_fine(db, fid)
        t0 = dt.datetime.strptime(f["ts"], "%Y-%m-%dT%H:%M:%SZ")
        t1 = dt.datetime.strptime(f["confirm_deadline"], "%Y-%m-%dT%H:%M:%SZ")
        assert (t1 - t0) == dt.timedelta(hours=12), (t1 - t0)
        assert f["status"] == "pending" and f["amount"] == 50
        print("ok BR-031 deadline == ts + 12h exactly")

        # BR-021 use_count bump; BR-035 pending excluded from the pot.
        assert (await queries.get_rule(db, rule))["use_count"] == 1
        assert await queries.pot_total(db) == 0
        print("ok BR-021 use_count bumped; BR-035 pending not in pot")

        # mark_paid only accepts owed (confirmed/upheld) fines.
        try:
            await fines.mark_paid(db, fid)
            assert False, "mark_paid(pending) should raise"
        except fines.FineError:
            pass
        print("ok mark_paid(pending) rejected")

        # BR-032 — sweep skips not-yet-due, then promotes overdue and returns exactly that id.
        assert await fines.sweep_due(db) == []
        await db.execute("UPDATE fines SET confirm_deadline=? WHERE id=?", (_past(), fid))
        await db.commit()
        assert await fines.sweep_due(db) == [fid]
        assert (await queries.get_fine(db, fid))["status"] == "confirmed"
        assert await queries.pot_total(db) == 50
        print("ok BR-032 sweep promotes & returns promoted id; pot=50")

        # BR-033 — can't dispute a confirmed fine.
        assert (await fines.dispute(db, fid)) is False
        print("ok BR-033 dispute(confirmed) -> False")

        # BR-036 — mark_paid flips once (True), double-tap is a no-op (False); dues clear.
        assert (await fines.mark_paid(db, fid)) is True
        assert (await fines.mark_paid(db, fid)) is False
        assert (await queries.member_dues(db, rohit))["fines"] == 0
        print("ok BR-036 mark_paid True then False; dues cleared")

        # BR-032 — a disputed pending fine is never swept.
        fid2 = await fines.create_fine(db, accused_id=amit, added_by=rohit, rule_id=rule)
        assert (await fines.dispute(db, fid2, "nope")) is True
        await db.execute("UPDATE fines SET confirm_deadline=? WHERE id=?", (_past(), fid2))
        await db.commit()
        assert fid2 not in await fines.sweep_due(db)
        assert (await queries.get_fine(db, fid2))["status"] == "disputed"
        print("ok BR-032 disputed fine never swept")

        # BR-001 — can't fine (or report as) an inactive member.
        ex = await queries.add_member(db, "ExTenant")
        await db.execute("UPDATE members SET is_active=0 WHERE id=?", (ex,))
        await db.commit()
        for accused, added_by, who in [(ex, amit, "accused"), (amit, ex, "accuser")]:
            try:
                await fines.create_fine(db, accused_id=accused, added_by=added_by, rule_id=rule)
                assert False, f"fine with inactive {who} should raise"
            except fines.FineError:
                pass
        print("ok BR-001 inactive accused/accuser rejected")

        # Ad-hoc fine (explicit amount, no rule) and the neither-rule-nor-amount guard.
        f3 = await queries.get_fine(db, await fines.create_fine(db, accused_id=rohit, added_by=amit, amount=20))
        assert f3["amount"] == 20 and f3["rule_id"] is None
        try:
            await fines.create_fine(db, accused_id=rohit, added_by=amit)
            assert False, "fine with neither rule nor amount should raise"
        except fines.FineError:
            pass
        print("ok ad-hoc fine; neither-rule-nor-amount rejected")

        print("\nPHASE-2 SMOKE: ALL CHECKS PASSED")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
