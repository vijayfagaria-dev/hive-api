"""F2 — JSON API (/api/*) smoke test: auth, role gating, data shapes, mutations.

    .venv/Scripts/python.exe tests/smoke_api.py
"""

import asyncio
import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_PATH"] = os.path.join(tempfile.gettempdir(), f"hive_api_{uuid.uuid4().hex}.db")
os.environ["WEBHOOK_SECRET"] = "testsecret"
os.environ["PROOF_STORAGE_DIR"] = os.path.join(tempfile.gettempdir(), f"hive_proofs_{uuid.uuid4().hex}")
os.environ["DUPLICATE_WINDOW_HOURS"] = "0"   # don't let dedupe block test repeats
os.environ["RATE_LIMIT_ENABLED"] = "false"  # many signups from one test client
os.environ.pop("TELEGRAM_BOT_TOKEN", None)

from app.db.session import create_all, session_scope  # noqa: E402
from app.repositories import members as members_repo  # noqa: E402
from app.repositories import rules as rules_repo  # noqa: E402
from app.services import accounts, complaints  # noqa: E402
from mailbox import Mailbox, signup  # noqa: E402

PASSWORDS = {"alice": "orbit-pw-123", "bob": "maple-pw-123", "carol": "comet-pw-123"}
KITCHEN = "KITCHEN_API_dishes"
NOISE = "NOISE_API_loud"
# A 1x1 JPEG-ish blob is enough — the API only checks content-type + size, never decodes.
FAKE_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 32


async def seed():
    await create_all()
    async with session_scope() as s:
        target = (await members_repo.add(s, name="Target", role="tenant")).id
        krule = (await rules_repo.add(s, category="kitchen", text=KITCHEN, fine_amount=50, is_favorite=True)).id
        await rules_repo.add(s, category="noise", text=NOISE, fine_amount=50)
        # A complaint NOT owned by our guest, for the pay ownership check.
        other = (await members_repo.add(s, name="Other", role="tenant")).id
        foreign = await complaints.create(
            s, accused_id=target, added_by=other, rule_id=krule,
            proofs=[{"source": "telegram", "ref": "seedphoto"}],
        )
        return {"target": target, "krule": krule, "foreign": foreign}


async def promote(username: str):
    async with session_scope() as s:
        member = await members_repo.get_by_username(s, username)
        await accounts.set_role(s, member, "tenant")


def main():
    s = asyncio.run(seed())
    from fastapi.testclient import TestClient
    from app.main import app

    box = Mailbox.install()
    with TestClient(app) as c:
        assert c.get("/api/auth/me").json()["member"] is None
        print("ok /api/auth/me is null when logged out")

        # Validation
        mail = {"email": "zoe@example.com"}
        assert c.post("/api/auth/register", json={"username": "ab", "password": "lime-tree-41", **mail}).status_code == 422
        assert c.post("/api/auth/register", json={"username": "zoe", "password": "x", **mail}).status_code == 422
        assert c.post("/api/auth/register", json={"username": "zoe", "password": "lime-tree-41"}).status_code == 422

        # Register (verified by emailed code) -> guest + session
        r = signup(c, box, "zoe", "lime-tree-41")
        assert r.status_code == 200 and r.json()["member"]["role"] == "guest"
        assert r.json()["member"]["emailVerified"] is True
        assert c.get("/api/auth/me").json()["member"]["username"] == "zoe"
        print("ok register -> verify code -> guest + session authenticates /api/auth/me")

        dup = {"username": "ZOE", "password": "lime-tree-41", "email": "zoe2@example.com"}
        assert c.post("/api/auth/register", json=dup).status_code == 409
        print("ok duplicate username -> 409")

        # Guest can't see the dashboard
        assert c.get("/api/dashboard").status_code == 403
        print("ok guest -> /api/dashboard 403")

        # Guests never see the flat's money — only their own statement (VIEW_FINANCES).
        for path in ("/api/expenses", "/api/balances", "/api/settle/preview", "/api/settle/open",
                     "/api/rent/2026-11", "/api/templates", "/api/recurring",
                     "/api/money/balances", "/api/money/ledger", "/api/money/settlements"):
            assert c.get(path).status_code == 403, path
        assert c.get("/api/balances/me").status_code == 200
        assert c.get("/api/money").status_code == 200
        print("ok guest -> flat-wide money reads 403; own statement 200")
        assert c.get("/api/complaints").status_code == 403
        print("ok guest -> /api/complaints (the Feed) 403")

        # /api/me payload shape
        me = c.get("/api/me").json()
        assert "kitchen" in me["rulesByCategory"] and any(x["text"] == KITCHEN for x in me["rulesByCategory"]["kitchen"])
        assert any(m["name"] == "Target" for m in me["members"])
        assert "hallOfShame" in me and "gettingHere" in me
        print("ok /api/me returns rules-by-category + members + shame + gettingHere")

        # Legacy /api/report is deprecated (proof is now mandatory).
        assert c.post("/api/report", json={"accusedId": s["target"], "ruleId": s["krule"]}).status_code == 400
        print("ok /api/report deprecated -> 400")

        # /api/complaints: proof is mandatory; with proof it files.
        assert c.post(
            "/api/complaints", data={"accusedId": s["target"], "ruleId": s["krule"]}
        ).status_code == 400  # no image
        filed = c.post(
            "/api/complaints", data={"accusedId": s["target"], "ruleId": s["krule"]},
            files={"images": ("p.jpg", FAKE_JPEG, "image/jpeg")},
        )
        assert filed.status_code == 200 and filed.json()["complaintId"]
        # Self-complaint rejected even with proof.
        assert c.post(
            "/api/complaints", data={"accusedId": me["member"]["id"], "ruleId": s["krule"]},
            files={"images": ("p.jpg", FAKE_JPEG, "image/jpeg")},
        ).status_code == 400
        # Non-image upload rejected.
        assert c.post(
            "/api/complaints", data={"accusedId": s["target"], "ruleId": s["krule"]},
            files={"images": ("e.txt", b"not an image", "text/plain")},
        ).status_code == 415
        print("ok /api/complaints requires an image; self-complaint -> 400; non-image -> 415")

        # Spot: category pre-filter
        spot = c.get("/api/spots/kitchen").json()
        rule_texts = [r["text"] for r in spot["rules"]]
        assert KITCHEN in rule_texts and NOISE not in rule_texts and spot["isTenant"] is False
        assert c.get("/api/spots/nope").status_code == 404
        print("ok /api/spots/<spot> pre-filters to the spot's category; 404 on unknown")

        # Pay: empty for a fresh guest; can't pay someone else's fine
        assert c.get("/api/pay").json()["unpaid"] == []
        assert c.post(f"/api/pay/{s['foreign']}").status_code == 404
        print("ok /api/pay empty for guest; paying someone else's fine -> 404")

        # Public stats (no auth needed)
        assert "pot" in c.get("/api/public/stats").json()
        print("ok /api/public/stats is public")

        # Promote zoe -> tenant; same session now reaches the dashboard
        asyncio.run(promote("zoe"))
        dash = c.get("/api/dashboard")
        assert dash.status_code == 200 and "pot" in dash.json() and "recentFines" in dash.json()
        print("ok after promotion, same session -> /api/dashboard 200")

        # The dashboard carries only a glance (<= 5); the Feed endpoint has the full list.
        feed = c.get("/api/complaints")
        assert feed.status_code == 200 and any(f["id"] == s["foreign"] for f in feed.json()["complaints"])
        assert len(dash.json()["recentFines"]) <= 5
        print("ok /api/complaints lists the feed; dashboard recentFines capped at 5")

        # --- Full complaint workflow: accept, dispute->vote, notifications, proof
        ids = {}
        for name in ("alice", "bob", "carol"):
            r = signup(c, box, name, PASSWORDS[name])
            assert r.status_code == 200, r.text
            ids[name] = r.json()["member"]["id"]

        # alice files about bob, with proof
        c.post("/api/auth/login", json={"username": "alice", "password": PASSWORDS["alice"]})
        filed = c.post(
            "/api/complaints", data={"accusedId": ids["bob"], "ruleId": s["krule"]},
            files={"images": ("a.jpg", FAKE_JPEG, "image/jpeg")},
        )
        cid = filed.json()["complaintId"]
        d = c.get(f"/api/complaints/{cid}").json()
        assert d["phase"] == "raised" and len(d["proofs"]) == 1 and d["proofs"][0]["url"]
        assert d["accuser"]["username"] == "alice" and d["accused"]["id"] == ids["bob"]
        assert d["canAccept"] is False and d["canDispute"] is False  # alice is the accuser
        proof_url = d["proofs"][0]["url"]
        print("ok complaint detail: phase/proof/accuser/accused/permissions")

        # proof bytes served to a logged-in member
        img = c.get(proof_url)
        assert img.status_code == 200 and img.headers["content-type"].startswith("image/")
        print("ok proof image served to a logged-in member")

        # bob accepts -> registered, no vote
        c.post("/api/auth/login", json={"username": "bob", "password": PASSWORDS["bob"]})
        d_bob = c.get(f"/api/complaints/{cid}").json()
        assert d_bob["canAccept"] is True and d_bob["canDispute"] is True
        assert c.post(f"/api/complaints/{cid}/accept").json()["accepted"] is True
        assert c.get(f"/api/complaints/{cid}").json()["phase"] == "registered"
        notifs = c.get("/api/notifications").json()
        assert notifs["unread"] >= 1 and any(n["kind"] == "complaint_raised" for n in notifs["notifications"])
        print("ok accused accepts -> registered; accused has an in-app notification")

        # alice files again (different rule), bob disputes -> voting; carol votes
        c.post("/api/auth/login", json={"username": "alice", "password": PASSWORDS["alice"]})
        noise_id = c.get("/api/me").json()["rulesByCategory"]["noise"][0]["id"]
        cid2 = c.post(
            "/api/complaints", data={"accusedId": ids["bob"], "ruleId": noise_id},
            files={"images": ("b.jpg", FAKE_JPEG, "image/jpeg")},
        ).json()["complaintId"]
        assert c.post(f"/api/complaints/{cid2}/dispute", json={}).status_code == 403  # accuser can't
        c.post("/api/auth/login", json={"username": "bob", "password": PASSWORDS["bob"]})
        assert c.post(f"/api/complaints/{cid2}/dispute", json={"reason": "wasn't me"}).json()["votingOpened"] is True
        assert c.get(f"/api/complaints/{cid2}").json()["phase"] == "voting"
        c.post("/api/auth/login", json={"username": "carol", "password": PASSWORDS["carol"]})
        v = c.post(f"/api/complaints/{cid2}/vote", json={"vote": "uphold"}).json()
        assert v["tally"]["uphold"] == 1 and v["status"] == "disputed"
        assert any(n["kind"] == "vote_requested" for n in c.get("/api/notifications").json()["notifications"])
        # mark one notification read
        first = c.get("/api/notifications").json()["notifications"][0]["id"]
        assert c.post(f"/api/notifications/{first}/read").json()["changed"] is True
        print("ok dispute->voting; vote recorded + voter notified; accuser blocked; notif read")

        # --- v4 notification channels: Web Push + email config ---
        assert c.get("/api/push/public-key").json()["key"] is None  # VAPID unconfigured in tests
        c.post("/api/auth/login", json={"username": "bob", "password": PASSWORDS["bob"]})
        sub = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "BKtest", "auth": "atest"}}
        assert c.post("/api/push/subscribe", json=sub).json()["ok"] is True
        assert c.post("/api/push/unsubscribe", json={"endpoint": sub["endpoint"]}).json()["ok"] is True
        assert c.post("/api/account/email", json={"email": "nope"}).status_code == 422
        assert c.post("/api/account/email", json={"email": "bob@example.com"}).json()["email"] == "bob@example.com"
        assert c.get("/api/auth/me").json()["member"]["email"] == "bob@example.com"
        # WhatsApp number: validated + normalized (channel skipped in tests, just stored).
        assert c.post("/api/account/whatsapp", json={"whatsapp": "12345"}).status_code == 422
        assert c.post("/api/account/whatsapp", json={"whatsapp": "+91 98765 43210"}).json()["whatsapp"] == "+919876543210"
        assert c.get("/api/auth/me").json()["member"]["whatsapp"] == "+919876543210"
        print("ok web-push subscribe/unsubscribe + email + whatsapp set/validate")

        # Other members' contact details are NOT exposed in the members list (privacy).
        me_payload = c.get("/api/me").json()
        assert all("email" not in m and "whatsapp" not in m for m in me_payload["members"])
        assert "email" in me_payload["member"] and "whatsapp" in me_payload["member"]  # but your own is
        print("ok own contacts visible to self; others' contacts not leaked")

        # --- bills (tenant-only; replaces the retired bot /bill) ---
        c.post("/api/auth/login", json={"username": "zoe", "password": "lime-tree-41"})  # zoe is a tenant
        bill = c.post("/api/bills", json={"type": "electricity", "total": 900, "month": "2026-06"})
        assert bill.status_code == 200 and bill.json()["billId"]
        assert c.post("/api/bills", json={"type": "nonsense", "total": 10, "month": "2026-06"}).status_code == 422
        c.post("/api/auth/login", json={"username": "bob", "password": PASSWORDS["bob"]})  # guest
        assert c.post("/api/bills", json={"type": "water", "total": 100, "month": "2026-06"}).status_code == 403
        print("ok bill create is tenant-only; bad type -> 422; guest -> 403")

        # Logout
        assert c.post("/api/auth/logout").json()["ok"] is True
        assert c.get("/api/auth/me").json()["member"] is None
        print("ok logout clears the session")

    print("\nF2 API SMOKE: ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
