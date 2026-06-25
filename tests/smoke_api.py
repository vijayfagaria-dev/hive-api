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
os.environ.pop("TELEGRAM_BOT_TOKEN", None)

from app import auth, db as dbm, fines, queries  # noqa: E402

KITCHEN = "KITCHEN_API_dishes"
NOISE = "NOISE_API_loud"


async def seed():
    db = await dbm.connect()
    try:
        target = await queries.add_member(db, "Target", role="tenant")
        krule = await queries.add_rule(db, "kitchen", KITCHEN, 50, is_favorite=True)
        await queries.add_rule(db, "noise", NOISE, 50)
        # A fine NOT owned by our guest, for the pay ownership check.
        other = await queries.add_member(db, "Other", role="tenant")
        foreign = await fines.create_fine(db, accused_id=target, added_by=other, rule_id=krule)
        return {"target": target, "krule": krule, "foreign": foreign}
    finally:
        await db.close()


async def promote(username: str):
    db = await dbm.connect()
    try:
        m = await queries.get_member_by_username(db, username)
        await queries.set_role(db, m["id"], "tenant")
    finally:
        await db.close()


def main():
    s = asyncio.run(seed())
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        assert c.get("/api/auth/me").json()["member"] is None
        print("ok /api/auth/me is null when logged out")

        # Validation
        assert c.post("/api/auth/register", json={"username": "ab", "password": "secret123"}).status_code == 422
        assert c.post("/api/auth/register", json={"username": "zoe", "password": "x"}).status_code == 422

        # Register -> guest + session
        r = c.post("/api/auth/register", json={"username": "zoe", "password": "zoepw123"})
        assert r.status_code == 200 and r.json()["member"]["role"] == "guest"
        assert c.get("/api/auth/me").json()["member"]["username"] == "zoe"
        print("ok register -> guest + session authenticates /api/auth/me")

        assert c.post("/api/auth/register", json={"username": "ZOE", "password": "zoepw123"}).status_code == 409
        print("ok duplicate username -> 409")

        # Guest can't see the dashboard
        assert c.get("/api/dashboard").status_code == 403
        print("ok guest -> /api/dashboard 403")

        # /api/me payload shape
        me = c.get("/api/me").json()
        assert "kitchen" in me["rulesByCategory"] and any(x["text"] == KITCHEN for x in me["rulesByCategory"]["kitchen"])
        assert any(m["name"] == "Target" for m in me["members"])
        assert "hallOfShame" in me and "gettingHere" in me
        print("ok /api/me returns rules-by-category + members + shame + gettingHere")

        # Report a fine
        assert c.post("/api/report", json={"accusedId": s["target"], "ruleId": s["krule"]}).json()["ok"] is True
        # Self-report rejected
        assert c.post("/api/report", json={"accusedId": me["member"]["id"], "ruleId": s["krule"]}).status_code == 400
        print("ok /api/report creates a fine; self-report -> 400")

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

        # Logout
        assert c.post("/api/auth/logout").json()["ok"] is True
        assert c.get("/api/auth/me").json()["member"] is None
        print("ok logout clears the session")

    print("\nF2 API SMOKE: ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
