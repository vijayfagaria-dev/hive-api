"""Notification outbox smoke test — enqueue in the request txn, drain in the dispatcher.

    .venv/bin/python3 tests/smoke_notify.py

Verifies the Phase-1 fix: notify_member records the in-app notification AND enqueues an
outbox row (no network in the caller's transaction); the background dispatcher then
drains the outbox in its own session (here all external channels are unconfigured, so
delivery is a no-op that still marks rows sent).
"""

import asyncio
import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_PATH"] = os.path.join(tempfile.gettempdir(), f"hive_notify_{uuid.uuid4().hex}.db")

from sqlalchemy import select  # noqa: E402

from app.db.models import NotificationOutbox  # noqa: E402
from app.db.session import create_all, dispose, session_scope  # noqa: E402
from app.domain.enums import FineStatus  # noqa: E402
from app.domain.time import now_iso  # noqa: E402
from app.repositories import devices as devices_repo  # noqa: E402
from app.repositories import fines as fines_repo  # noqa: E402
from app.repositories import members as members_repo  # noqa: E402
from app.repositories import notifications as notifications_repo  # noqa: E402
from app.services import notifications  # noqa: E402


async def outbox_rows():
    async with session_scope() as s:
        return list(await s.scalars(select(NotificationOutbox)))


async def main():
    await create_all()
    try:
        async with session_scope() as s:
            amit = await members_repo.add(s, name="Amit", role="tenant")
            amit_id = amit.id
            fine = await fines_repo.insert(
                s, member_id=amit_id, rule_id=None, amount=50, added_by=amit_id,
                status=FineStatus.CONFIRMED, ts=now_iso(), confirm_deadline=None,
            )
            fid = fine.id

        # notify_member: in-app row + one enqueued outbox row, both in this transaction.
        async with session_scope() as s:
            member = await members_repo.get(s, amit_id)
            await notifications.notify_member(
                s, member, kind="complaint_raised", title="🚨 Test", body="hi", fine_id=fid,
            )
        async with session_scope() as s:
            inbox = await notifications_repo.list_for(s, amit_id)
        assert len(inbox) == 1 and inbox[0].kind == "complaint_raised"
        rows = await outbox_rows()
        assert len(rows) == 1
        r = rows[0]
        assert r.status == "pending" and r.attempts == 0
        assert r.title == "🚨 Test" and r.tag == f"complaint-{fid}"
        print("ok notify_member: in-app row + 1 pending outbox row (no inline send)")

        # Dispatch drains it (channels unconfigured -> no-op delivery -> marked sent).
        n = await notifications.dispatch_outbox()
        assert n == 1
        rows = await outbox_rows()
        assert rows[0].status == "sent" and rows[0].sent_at is not None and rows[0].attempts == 1
        print("ok dispatch_outbox: pending -> sent (attempts=1, sent_at set)")

        # Nothing left to do on the next pass.
        assert (await notifications.dispatch_outbox()) == 0
        print("ok dispatch_outbox: idempotent (0 on an empty queue)")

        # notify_members (plural) enqueues one row per recipient.
        async with session_scope() as s:
            rohit = await members_repo.add(s, name="Rohit", role="tenant")
            priya = await members_repo.add(s, name="Priya", role="tenant")
        async with session_scope() as s:
            members = [await members_repo.get(s, rohit.id), await members_repo.get(s, priya.id)]
            await notifications.notify_members(s, members, kind="vote_requested", title="🗳️ Vote", body="x", fine_id=fid)
        pending = [r for r in await outbox_rows() if r.status == "pending"]
        assert len(pending) == 2
        assert (await notifications.dispatch_outbox()) == 2
        assert all(r.status == "sent" for r in await outbox_rows())
        print("ok notify_members: one outbox row per recipient, all dispatched")

        # --- Phase 4b: provider-agnostic devices + pluggable channel registry ---
        assert {c.name for c in notifications.CHANNELS} == {"webpush", "fcm", "email", "whatsapp"}
        async with session_scope() as s:
            await devices_repo.upsert(
                s, member_id=amit_id, provider="webpush", platform="web",
                token="https://push.example/ep1", p256dh="k", auth="a",
            )
            await devices_repo.upsert(
                s, member_id=amit_id, provider="fcm", platform="android", token="fcm-token-1",
            )
        async with session_scope() as s:
            web = await devices_repo.list_for(s, amit_id, "webpush")
            fcm = await devices_repo.list_for(s, amit_id, "fcm")
        assert len(web) == 1 and web[0].p256dh == "k"
        assert len(fcm) == 1 and fcm[0].token == "fcm-token-1" and fcm[0].p256dh is None
        # upsert by token re-points (no duplicate); rotated tokens never rejected
        async with session_scope() as s:
            await devices_repo.upsert(s, member_id=rohit.id, provider="fcm", platform="ios", token="fcm-token-1")
        async with session_scope() as s:
            assert len(await devices_repo.list_for(s, amit_id, "fcm")) == 0  # moved to rohit
            assert len(await devices_repo.list_for(s, rohit.id, "fcm")) == 1
            await devices_repo.delete_by_token(s, "fcm-token-1")
        async with session_scope() as s:
            assert len(await devices_repo.list_for(s, rohit.id, "fcm")) == 0
        print("ok devices: upsert/list/re-point/delete across webpush + fcm providers")

        print("\nNOTIFY SMOKE: ALL CHECKS PASSED")
    finally:
        await dispose()


if __name__ == "__main__":
    asyncio.run(main())
