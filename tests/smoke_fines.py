"""Complaint lifecycle smoke test — the service + repositories + ORM.

    .venv/bin/python3 tests/smoke_fines.py

Each operation runs in its own session scope (mirrors a request), so we exercise
the real transactional unit of work. Covers proof-required, accept, deny→vote,
finalize, the sweeps, audit events, and in-app notifications. Anti-spam guards are
disabled here (set to 0) and exercised via the API in smoke_api.py.
"""

import asyncio
import datetime as dt
import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_PATH"] = os.path.join(tempfile.gettempdir(), f"hive_smoke_{uuid.uuid4().hex}.db")
os.environ["COOLING_HOURS"] = "12"
os.environ["VOTE_WINDOW_HOURS"] = "24"
os.environ["DUPLICATE_WINDOW_HOURS"] = "0"
os.environ["MAX_COMPLAINTS_PER_DAY"] = "0"

from app.core.errors import DomainError, Forbidden, NotFound  # noqa: E402
from app.db.session import create_all, dispose, session_scope  # noqa: E402
from app.repositories import fines as fines_repo  # noqa: E402
from app.repositories import members as members_repo  # noqa: E402
from app.repositories import notifications as notifications_repo  # noqa: E402
from app.repositories import rules as rules_repo  # noqa: E402
from app.services import complaints  # noqa: E402

PROOF = [{"source": "telegram", "ref": "AgACphoto123", "content_type": "image/jpeg"}]


def _past(hours: int = 1) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- per-operation helpers (each its own committed unit of work) ------------

async def add_member(name):
    async with session_scope() as s:
        return (await members_repo.add(s, name=name)).id


async def add_rule(**kw):
    async with session_scope() as s:
        return (await rules_repo.add(s, **kw)).id


async def create(**kw):
    async with session_scope() as s:
        return await complaints.create(s, **kw)


async def get_fine(fid):
    async with session_scope() as s:
        return await fines_repo.get(s, fid)


async def accept(fid, by):
    async with session_scope() as s:
        return await complaints.accept(s, fid, by)


async def dispute(fid, by):
    async with session_scope() as s:
        return await complaints.dispute(s, fid, by_member=by)


async def vote(fid, voter, choice):
    async with session_scope() as s:
        return await complaints.cast_vote(s, fid, voter, choice)


async def sweep_due():
    async with session_scope() as s:
        return await complaints.sweep_due(s)


async def sweep_votes():
    async with session_scope() as s:
        return await complaints.sweep_votes(s)


async def sweep_overdue():
    async with session_scope() as s:
        return await complaints.sweep_overdue(s)


async def mark_paid(fid):
    async with session_scope() as s:
        return await complaints.mark_paid(s, fid)


async def mark_fines_paid(mid, ids):
    async with session_scope() as s:
        return await complaints.mark_fines_paid(s, mid, ids)


async def set_field(fid, **fields):
    async with session_scope() as s:
        fine = await fines_repo.get(s, fid)
        for key, value in fields.items():
            setattr(fine, key, value)


async def set_active(mid, active):
    async with session_scope() as s:
        (await members_repo.get(s, mid)).is_active = active


async def event_types(fid):
    async with session_scope() as s:
        return [e.type for e in await fines_repo.list_events(s, fid)]


async def notif_kinds(mid):
    async with session_scope() as s:
        return [n.kind for n in await notifications_repo.list_for(s, mid)]


async def proofs_count(fid):
    async with session_scope() as s:
        return await fines_repo.list_proofs(s, fid)


async def pot():
    async with session_scope() as s:
        return await fines_repo.pot_total(s)


async def rule_use(rid):
    async with session_scope() as s:
        return (await rules_repo.get(s, rid)).use_count


async def unpaid_ids(mid):
    async with session_scope() as s:
        return [r.id for r in await fines_repo.list_unpaid_owed(s, mid)]


async def main() -> None:
    await create_all()
    try:
        amit = await add_member("Amit")
        rohit = await add_member("Rohit")
        priya = await add_member("Priya")
        rule = await add_rule(category="kitchen", text="Left dishes", fine_amount=50, is_favorite=True)

        # BR-100 — no proof, no complaint.
        try:
            await create(accused_id=rohit, added_by=amit, rule_id=rule, proofs=[])
            assert False
        except DomainError:
            pass
        print("ok no-proof complaint rejected")

        # Self-complaint rejected.
        try:
            await create(accused_id=amit, added_by=amit, rule_id=rule, proofs=PROOF)
            assert False
        except DomainError:
            pass
        print("ok self-complaint rejected")

        # Create: pending + deadline == ts+12h; proof + audit + accused notified.
        fid = await create(accused_id=rohit, added_by=amit, rule_id=rule, proofs=PROOF)
        f = await get_fine(fid)
        t0 = dt.datetime.strptime(f.ts, "%Y-%m-%dT%H:%M:%SZ")
        t1 = dt.datetime.strptime(f.confirm_deadline, "%Y-%m-%dT%H:%M:%SZ")
        assert (t1 - t0) == dt.timedelta(hours=12)
        assert f.status == "pending" and f.amount == 50
        assert len(await proofs_count(fid)) == 1
        assert {"raised", "accused_notified"} <= set(await event_types(fid))
        assert "complaint_raised" in await notif_kinds(rohit)
        assert await rule_use(rule) == 1
        assert await pot() == 0
        print("ok create: pending/deadline/proof/audit/notify; use_count bumped; pot=0")

        # mark_paid(pending) rejected.
        try:
            await mark_paid(fid)
            assert False
        except DomainError:
            pass
        print("ok mark_paid(pending) rejected")

        # Accept: only the accused (Forbidden otherwise); registers without a vote.
        try:
            await accept(fid, amit)
            assert False
        except Forbidden:
            pass
        assert (await accept(fid, rohit)) is True
        f = await get_fine(fid)
        assert f.status == "confirmed" and f.resolution == "accepted"
        # Bug 2: acceptance registers an OWED obligation with a pay-by — it does NOT settle.
        assert f.payment_status == "owed" and f.pay_by is not None and f.paid is False
        assert await pot() == 50
        assert (await accept(fid, rohit)) is False
        print("ok accept -> registered (confirmed) + OWED (pay-by set, unpaid); pot=50")

        # Bug 4 — only the ACCUSED may respond. The accuser and a neutral member are
        # Forbidden from denying; the complaint stays pending until the accused acts.
        fidp = await create(accused_id=rohit, added_by=amit, rule_id=rule, proofs=PROOF)
        for actor in (amit, priya):  # accuser, then a neutral third party
            try:
                await dispute(fidp, actor)
                assert False
            except Forbidden:
                pass
        assert (await get_fine(fidp)).status == "pending"  # nobody but the accused moved it
        assert (await dispute(fidp, rohit)) is True          # the accused can deny
        assert (await get_fine(fidp)).status == "disputed"
        print("ok Bug4: only the accused can deny (accuser + neutral Forbidden)")

        # Deny -> vote (Priya eligible) -> uphold finalizes.
        fid2 = await create(accused_id=rohit, added_by=amit, rule_id=rule, proofs=PROOF)
        assert (await dispute(fid2, rohit)) is True
        f2 = await get_fine(fid2)
        assert f2.status == "disputed" and f2.vote_deadline is not None
        assert {"disputed", "voting_started", "members_notified"} <= set(await event_types(fid2))
        assert "vote_requested" in await notif_kinds(priya)
        await set_field(fid2, confirm_deadline=_past())
        assert fid2 not in await sweep_due()  # disputed never auto-confirms
        assert (await get_fine(fid2)).status == "disputed"
        for voter in (amit, rohit):
            try:
                await vote(fid2, voter, "uphold")
                assert False
            except DomainError:
                pass
        assert (await vote(fid2, priya, "uphold")) == "upheld"
        assert (await get_fine(fid2)).status == "upheld"
        assert await pot() == 100
        print("ok deny->vote->upheld; eligibility; no-sweep; pot=100")

        # Deny -> vote -> void.
        fid3 = await create(accused_id=rohit, added_by=amit, rule_id=rule, proofs=PROOF)
        await dispute(fid3, rohit)
        assert (await vote(fid3, priya, "void")) == "void"
        assert (await get_fine(fid3)).status == "void"
        assert await pot() == 100
        print("ok deny->vote->void; void excluded from pot")

        # Deny with no eligible voters -> void.
        await set_active(priya, False)
        fid4 = await create(accused_id=rohit, added_by=amit, rule_id=rule, proofs=PROOF)
        assert (await dispute(fid4, rohit)) is True
        assert (await get_fine(fid4)).status == "void"
        await set_active(priya, True)
        print("ok deny with no eligible voters -> void")

        # Vote-window sweep finalizes an expired, un-voted vote (-> void).
        fid5 = await create(accused_id=rohit, added_by=amit, rule_id=rule, proofs=PROOF)
        await dispute(fid5, rohit)
        await set_field(fid5, vote_deadline=_past())
        assert fid5 in await sweep_votes()
        assert (await get_fine(fid5)).status == "void"
        print("ok vote-window sweep finalizes expired vote")

        # Cooling sweep auto-confirms an untouched pending complaint.
        fid6 = await create(accused_id=rohit, added_by=amit, rule_id=rule, proofs=PROOF)
        await set_field(fid6, confirm_deadline=_past())
        assert await sweep_due() == [fid6]
        f6 = await get_fine(fid6)
        assert f6.status == "confirmed" and f6.resolution == "auto_confirmed"
        assert f6.payment_status == "owed" and f6.pay_by is not None  # Bug 2: auto-confirm registers a debt
        assert "auto_confirmed" in await event_types(fid6)
        print("ok cooling sweep auto-confirms (resolution=auto_confirmed) + OWED")

        # mark_paid flips once, double-tap no-ops; OWED -> SETTLED.
        assert (await mark_paid(fid6)) is True
        assert (await mark_paid(fid6)) is False
        f6 = await get_fine(fid6)
        assert f6.paid is True and f6.payment_status == "settled" and f6.paid_at is not None
        assert fid6 not in await unpaid_ids(rohit)
        print("ok mark_paid True then False; OWED -> SETTLED; fine drops out of dues")

        # Inactive accused/accuser rejected.
        ex = await add_member("ExTenant")
        await set_active(ex, False)
        for accused, added_by in [(ex, amit), (amit, ex)]:
            try:
                await create(accused_id=accused, added_by=added_by, rule_id=rule, proofs=PROOF)
                assert False
            except DomainError:
                pass
        print("ok inactive accused/accuser rejected")

        # Ad-hoc complaint (amount, no rule) + neither-rule-nor-amount guard.
        fid7 = await create(accused_id=rohit, added_by=priya, amount=20, proofs=PROOF)
        f7 = await get_fine(fid7)
        assert f7.amount == 20 and f7.rule_id is None
        try:
            await create(accused_id=rohit, added_by=amit, proofs=PROOF)
            assert False
        except DomainError:
            pass
        print("ok ad-hoc complaint; neither-rule-nor-amount rejected")

        # Bug 1 — each fine settles INDEPENDENTLY. Two owed fines on Rohit; paying only
        # the second must charge exactly ₹100, never the ₹150 total.
        fa = await create(accused_id=rohit, added_by=amit, rule_id=rule, proofs=PROOF)  # ₹50
        fb = await create(accused_id=rohit, added_by=priya, amount=100, proofs=PROOF)    # ₹100
        assert await accept(fa, rohit) and await accept(fb, rohit)                       # both registered
        res = await mark_fines_paid(rohit, [fb])                                         # pay only the second
        assert res == {"paid": [fb], "count": 1, "totalPaid": 100}
        unpaid = await unpaid_ids(rohit)
        assert fb not in unpaid and fa in unpaid  # only fb settled; fa still owed
        print("ok Bug1: paying one of two fines charges ₹100 (that fine only), not ₹150")

        # owed_fines_for validation: not-your-fine and not-payable are both rejected.
        fc = await create(accused_id=amit, added_by=rohit, rule_id=rule, proofs=PROOF)   # Amit's fine
        try:
            await mark_fines_paid(rohit, [fc]); assert False
        except NotFound:
            pass
        fd = await create(accused_id=rohit, added_by=amit, amount=30, proofs=PROOF)      # pending (not registered)
        try:
            await mark_fines_paid(rohit, [fd]); assert False
        except DomainError:
            pass
        print("ok Bug1: paying another's fine -> 404; paying an unregistered fine -> 400")

        # Bug 2 — the payment state machine end to end.
        fe = await create(accused_id=rohit, added_by=amit, amount=70, proofs=PROOF)
        try:
            await mark_paid(fe); assert False           # not registered yet -> not payable
        except DomainError:
            pass
        await accept(fe, rohit)
        f = await get_fine(fe)
        assert f.payment_status == "owed" and f.paid is False and f.paid_at is None
        assert (await mark_paid(fe)) is True
        f = await get_fine(fe)
        assert f.payment_status == "settled" and f.paid is True and f.paid_at is not None
        assert (await mark_paid(fe)) is False           # already settled
        assert {"payment_due", "paid"} <= set(await event_types(fe))
        print("ok Bug2: NOT_OWED->(register)->OWED->(pay)->SETTLED; events logged")

        # Bug 2 — OWED past its pay-by goes OVERDUE via the sweep, and is still payable.
        fg = await create(accused_id=rohit, added_by=amit, amount=90, proofs=PROOF)
        await accept(fg, rohit)
        await set_field(fg, pay_by=_past())
        assert fg in await sweep_overdue()
        assert (await get_fine(fg)).payment_status == "overdue"
        assert "overdue" in await event_types(fg)
        assert (await mark_paid(fg)) is True
        assert (await get_fine(fg)).payment_status == "settled"
        print("ok Bug2: OWED past pay-by -> OVERDUE (sweep); overdue still pays -> SETTLED")

        print("\nFINES/COMPLAINT SMOKE: ALL CHECKS PASSED")
    finally:
        await dispose()


if __name__ == "__main__":
    asyncio.run(main())
