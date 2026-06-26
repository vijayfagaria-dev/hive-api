"""Rule-proposal lifecycle smoke test — service + repositories + ORM.

    .venv/bin/python3 tests/smoke_proposals.py

Covers: create/submit, tenant-only voting (one vote, changeable), close+evaluate
(passed / rejected / expired by quorum+majority), auto-merge into the rule book +
immutable rule_versions, modify/delete merges, rollback, comments, admin controls,
the sweep, optimistic locking, and anti-spam. Each op runs in its own session scope.
"""

import asyncio
import datetime as dt
import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_PATH"] = os.path.join(tempfile.gettempdir(), f"hive_prop_{uuid.uuid4().hex}.db")
os.environ["PROPOSAL_QUORUM"] = "2"
os.environ["PROPOSAL_PASS_PCT"] = "60"
os.environ["PROPOSAL_MIN_YES"] = "2"
os.environ["PROPOSAL_VOTING_HOURS"] = "72"
os.environ["PROPOSAL_MAX_PER_DAY"] = "50"     # don't let the rate-limit block the test
os.environ["PROPOSAL_MIN_BODY_LEN"] = "10"

from app.core.errors import Conflict, DomainError, Forbidden, Unprocessable  # noqa: E402
from app.db.session import create_all, dispose, session_scope  # noqa: E402
from app.domain.enums import ProposalStatus  # noqa: E402
from app.repositories import members as members_repo  # noqa: E402
from app.repositories import notifications as notifications_repo  # noqa: E402
from app.repositories import proposals as proposals_repo  # noqa: E402
from app.repositories import rule_versions as rule_versions_repo  # noqa: E402
from app.repositories import rules as rules_repo  # noqa: E402
from app.services import proposals, rulebook  # noqa: E402

BODY = "A proper rationale for the proposed change."


def _past() -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


async def add_member(name, role="tenant"):
    async with session_scope() as s:
        return await members_repo.add(s, name=name, role=role)


async def create(**kw):
    async with session_scope() as s:
        return await proposals.create(s, **kw)


async def get(pid):
    async with session_scope() as s:
        return await proposals_repo.get(s, pid)


async def submit(pid, by):
    async with session_scope() as s:
        return await proposals.submit_proposal(s, await proposals_repo.get(s, pid), by_member=by)


async def vote(pid, voter_id, choice):
    async with session_scope() as s:
        return await proposals.vote(s, pid, voter_id, choice)


async def close(pid):
    async with session_scope() as s:
        return await proposals.close_and_evaluate(s, await proposals_repo.get(s, pid))


async def set_field(pid, **fields):
    async with session_scope() as s:
        p = await proposals_repo.get(s, pid)
        for k, v in fields.items():
            setattr(p, k, v)


async def active_rule_count():
    async with session_scope() as s:
        return len(await rules_repo.list_all(s))


async def event_types(pid):
    async with session_scope() as s:
        return [e.type for e in await proposals_repo.list_events(s, pid)]


async def notif_kinds(mid):
    async with session_scope() as s:
        return [n.kind for n in await notifications_repo.list_for(s, mid)]


async def main():
    await create_all()
    try:
        amit = await add_member("Amit")
        rohit = await add_member("Rohit")
        priya = await add_member("Priya")
        zoe = await add_member("Zoe", role="guest")

        # --- Create + submit -> voting (review off) -----------------------------
        p1 = await create(proposer_id=amit.id, type="new_rule", title="No loud blender after 10pm",
                          body=BODY, proposed_category="kitchen", proposed_text="No loud blender after 10pm", proposed_amount=30)
        pr = await get(p1)
        assert pr.status == ProposalStatus.VOTING and pr.voting_closes_at
        assert {"created", "submitted", "voting_opened"} <= set(await event_types(p1))
        assert "proposal_voting" in await notif_kinds(priya.id)
        print("ok create -> voting; events + tenant notified")

        # --- Voting: tenants only, one vote, changeable ------------------------
        try:
            await vote(p1, zoe.id, "yes"); assert False
        except Forbidden:
            pass
        await vote(p1, amit.id, "yes")
        await vote(p1, rohit.id, "yes")
        await vote(p1, priya.id, "yes")
        await vote(p1, rohit.id, "no")   # change vote
        await vote(p1, rohit.id, "no")   # duplicate -> still one row
        async with session_scope() as s:
            t = await proposals_repo.vote_tally(s, p1)
        assert t == {"yes": 2, "no": 1, "abstain": 0, "total": 3}, t
        print("ok guest blocked; one-vote-per-tenant; vote change updates tally")

        # --- Close -> PASSED -> merged into the rule book + version 1 ----------
        await set_field(p1, voting_closes_at=_past())
        assert (await close(p1)) == ProposalStatus.PASSED   # 67% yes, >=2 yes, quorum 3
        pr = await get(p1)
        assert pr.merged_rule_id and pr.resolved_at
        assert await active_rule_count() == 1
        async with session_scope() as s:
            versions = await rule_versions_repo.list_for(s, pr.merged_rule_id)
        assert len(versions) == 1 and versions[0].version_number == 1 and versions[0].active
        assert {"voting_closed", "passed", "merged"} <= set(await event_types(p1))
        assert "rule_published" in await notif_kinds(priya.id)
        new_rule_id = pr.merged_rule_id
        print("ok passed -> rule merged + rule_version v1 + everyone notified")

        # --- REJECTED (majority no) -------------------------------------------
        p2 = await create(proposer_id=amit.id, type="new_rule", title="Ban music",
                          body=BODY, proposed_category="noise", proposed_text="No music ever", proposed_amount=20)
        await vote(p2, amit.id, "yes"); await vote(p2, rohit.id, "no"); await vote(p2, priya.id, "no")
        await set_field(p2, voting_closes_at=_past())
        assert (await close(p2)) == ProposalStatus.REJECTED
        assert await active_rule_count() == 1  # nothing added
        print("ok majority-no -> rejected, rule book unchanged")

        # --- EXPIRED (no quorum) ----------------------------------------------
        p3 = await create(proposer_id=amit.id, type="new_rule", title="Tiny rule",
                          body=BODY, proposed_category="general", proposed_text="Water the plants", proposed_amount=10)
        await vote(p3, amit.id, "yes")  # 1 < quorum 2
        await set_field(p3, voting_closes_at=_past())
        assert (await close(p3)) == ProposalStatus.EXPIRED
        print("ok no quorum -> expired")

        # --- MODIFY merge -> version 2 ----------------------------------------
        p4 = await create(proposer_id=amit.id, type="modify_rule", title="Tighten blender rule",
                          body=BODY, target_rule_id=new_rule_id,
                          proposed_text="No loud appliances after 10pm", proposed_amount=40)
        for m in (amit, rohit, priya):
            await vote(p4, m.id, "yes")
        await set_field(p4, voting_closes_at=_past())
        assert (await close(p4)) == ProposalStatus.PASSED
        async with session_scope() as s:
            rule = await rules_repo.get(s, new_rule_id)
            versions = await rule_versions_repo.list_for(s, new_rule_id)
        assert rule.text == "No loud appliances after 10pm" and rule.fine_amount == 40
        assert len(versions) == 2 and versions[0].version_number == 2
        print("ok modify -> rule updated + rule_version v2")

        # --- DELETE merge -> rule deactivated ---------------------------------
        p5 = await create(proposer_id=amit.id, type="delete_rule", title="Drop the blender rule",
                          body=BODY, target_rule_id=new_rule_id)
        for m in (amit, rohit, priya):
            await vote(p5, m.id, "yes")
        await set_field(p5, voting_closes_at=_past())
        assert (await close(p5)) == ProposalStatus.PASSED
        assert await active_rule_count() == 0  # deactivated -> out of the book
        async with session_scope() as s:
            assert (await rules_repo.get(s, new_rule_id)).is_active is False
        print("ok delete -> rule deactivated (kept for FK/history)")

        # --- Rollback restores a prior version --------------------------------
        async with session_scope() as s:
            versions = await rule_versions_repo.list_for(s, new_rule_id)  # v3(deleted), v2, v1
            v1_id = [v.id for v in versions if v.version_number == 1][0]
            new_v = await rulebook.rollback(s, new_rule_id, v1_id, amit)
            restored = await rules_repo.get(s, new_rule_id)
        assert restored.is_active is True and restored.text == "No loud blender after 10pm"
        assert new_v.version_number == 4
        print("ok rollback restores rule + appends a new version")

        # --- Optimistic lock on draft edit ------------------------------------
        d = await create(proposer_id=amit.id, type="new_rule", title="Draft rule",
                         body=BODY, proposed_category="general", proposed_text="Draft text one", proposed_amount=5, submit=False)
        async with session_scope() as s:
            p = await proposals_repo.get(s, d)
            try:
                await proposals.update(s, p, amit, expected_version=999, title="x")
                assert False
            except Conflict:
                pass
        print("ok optimistic-lock conflict on stale version")

        # --- Admin: approve (review path), extend, freeze, cancel, force-merge, reject
        # approve: force into pending_review then approve -> voting
        await set_field(d, status=ProposalStatus.PENDING_REVIEW)
        async with session_scope() as s:
            assert (await proposals.approve(s, d, amit)) == ProposalStatus.VOTING
        # guest can't approve
        e = await create(proposer_id=amit.id, type="new_rule", title="Another",
                         body=BODY, proposed_category="general", proposed_text="Draft text two", proposed_amount=5, submit=False)
        await set_field(e, status=ProposalStatus.PENDING_REVIEW)
        async with session_scope() as s:
            try:
                await proposals.approve(s, e, zoe); assert False
            except Forbidden:
                pass
        # extend
        async with session_scope() as s:
            before = (await proposals_repo.get(s, d)).voting_closes_at
            await proposals.extend(s, d, amit, 24)
            after = (await proposals_repo.get(s, d)).voting_closes_at
        assert after > before
        # freeze -> sweep skips it (use a far-future "now" so closes_at < now holds;
        # the only reason d is excluded is the freeze flag)
        await set_field(d, voting_closes_at=_past())
        async with session_scope() as s:
            await proposals.freeze(s, d, amit, True)
        async with session_scope() as s:
            assert d not in await proposals_repo.due_ids(s, "2099-12-31T23:59:59Z")
        print("ok admin approve (+guest blocked), extend, freeze-skips-sweep")

        # force-merge an unpopular proposal
        async with session_scope() as s:
            await proposals.freeze(s, d, amit, False)
        async with session_scope() as s:
            assert (await proposals.force_merge(s, d, amit)) == ProposalStatus.PASSED
        # reject a pending one
        async with session_scope() as s:
            assert (await proposals.reject(s, e, amit)) == ProposalStatus.REJECTED
        print("ok force-merge + admin reject")

        # --- Comments: add / edit / delete ------------------------------------
        c = await create(proposer_id=amit.id, type="new_rule", title="Comment target",
                         body=BODY, proposed_category="general", proposed_text="Commentable rule", proposed_amount=5)
        async with session_scope() as s:
            cid = await proposals.add_comment(s, c, rohit, "I support this.")
        async with session_scope() as s:
            await proposals.edit_comment(s, cid, rohit, "Edited: strongly support.")
            try:
                await proposals.edit_comment(s, cid, priya, "hijack"); assert False
            except Forbidden:
                pass
            await proposals.delete_comment(s, cid, rohit)
        async with session_scope() as s:
            rows = await proposals_repo.list_comments(s, c)
        assert len(rows) == 1 and rows[0].deleted and rows[0].edited_at
        # proposer got a comment notification
        assert "proposal_comment" in await notif_kinds(amit.id)
        print("ok comments: add/edit(author-only)/soft-delete + proposer notified")

        # --- Anti-spam duplicate ----------------------------------------------
        await create(proposer_id=priya.id, type="new_rule", title="Dup A",
                     body=BODY, proposed_category="general", proposed_text="Unique dup text", proposed_amount=5)
        try:
            await create(proposer_id=priya.id, type="new_rule", title="Dup B",
                         body=BODY, proposed_category="general", proposed_text="unique DUP text", proposed_amount=5)
            assert False
        except DomainError:
            pass
        print("ok duplicate-proposal guard (case-insensitive)")

        # --- sweep_due closes an elapsed vote ---------------------------------
        sp = await create(proposer_id=amit.id, type="new_rule", title="Sweepable",
                          body=BODY, proposed_category="general", proposed_text="Sweep me", proposed_amount=5)
        await vote(sp, amit.id, "yes"); await vote(sp, rohit.id, "yes")
        await set_field(sp, voting_closes_at=_past())
        async with session_scope() as s:
            closed = await proposals.sweep_due(s)
        assert sp in closed
        assert (await get(sp)).status == ProposalStatus.PASSED
        print("ok sweep_due closes + evaluates an elapsed proposal")

        # --- submit guard: body too short -------------------------------------
        short = await create(proposer_id=amit.id, type="new_rule", title="Short",
                             body="hi", proposed_category="general", proposed_text="short body rule", proposed_amount=5, submit=False)
        try:
            await submit(short, amit); assert False
        except Unprocessable:
            pass
        print("ok submit blocked when rationale too short")

        print("\nPROPOSALS SMOKE: ALL CHECKS PASSED")
    finally:
        await dispose()


if __name__ == "__main__":
    asyncio.run(main())
