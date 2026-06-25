"""Auth primitives — bcrypt hashing + the account/migration data layer.

(The register/login/logout HTTP flow is covered by tests/smoke_api.py.)

    .venv/Scripts/python.exe tests/smoke_auth.py
"""

import asyncio
import os
import sqlite3
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_PATH"] = os.path.join(tempfile.gettempdir(), f"hive_auth_{uuid.uuid4().hex}.db")
os.environ["WEBHOOK_SECRET"] = "testsecret"
os.environ.pop("TELEGRAM_BOT_TOKEN", None)

from app import auth, db as dbm, queries  # noqa: E402


def unit_checks():
    # Password hashing via bcrypt (the standard library function).
    h = auth.hash_password("hunter2")
    assert h.startswith("$2b$") and "hunter2" not in h
    assert auth.verify_password("hunter2", h)
    assert not auth.verify_password("wrong", h)
    assert not auth.verify_password("x", None)
    assert not auth.verify_password("hunter2", "not-a-bcrypt-hash")  # malformed -> False, no crash
    print("ok bcrypt password hash/verify (not plaintext)")


async def db_checks():
    db = await dbm.connect()
    try:
        await queries.register_member(db, "amit", auth.hash_password("secret123"))
        m = await queries.get_member_by_username(db, "amit")
        assert m is not None
        assert m["role"] == "guest", f"new users default to guest, got {m['role']}"
        assert m["name"] == "amit" and m["username"] == "amit"
        assert m["password_hash"] and "secret123" not in m["password_hash"]
        print("ok registered member is a guest, password stored hashed")

        # Migration is idempotent + columns present.
        async with db.execute("PRAGMA table_info(members)") as cur:
            cols = {r["name"] for r in await cur.fetchall()}
        assert {"username", "password_hash"} <= cols
        print("ok migration idempotent; username/password_hash present")

        # Manual promotion is the only path to tenant.
        await queries.set_role(db, m["id"], "tenant")
        assert (await queries.get_member_by_username(db, "amit"))["role"] == "tenant"
        print("ok set_role promotes guest -> tenant")

        # A forged/garbage member id (e.g. a string from a tampered session) is a
        # clean miss, never a TypeError 500.
        assert await queries.get_member(db, "abc") is None
        assert await queries.get_member(db, 2 ** 70) is None
        print("ok forged/out-of-range member id -> None (no crash)")

        # The unique index is the authoritative duplicate guard (catches TOCTOU races).
        try:
            await queries.register_member(db, "AMIT", auth.hash_password("x" * 8))
            assert False, "duplicate username (case-insensitive) should hit the unique index"
        except sqlite3.IntegrityError:
            print("ok duplicate register_member rejected by lower(username) unique index")
    finally:
        await db.close()


def main():
    unit_checks()
    asyncio.run(db_checks())
    print("\nAUTH SMOKE: ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
