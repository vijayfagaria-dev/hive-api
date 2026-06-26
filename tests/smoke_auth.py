"""Auth primitives — bcrypt hashing + the account data layer (SQLAlchemy ORM).

    .venv/bin/python3 tests/smoke_auth.py
"""

import asyncio
import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_PATH"] = os.path.join(tempfile.gettempdir(), f"hive_auth_{uuid.uuid4().hex}.db")
os.environ["SECRET_KEY"] = "testsecret"

from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

from app.core import security  # noqa: E402
from app.db.session import create_all, dispose, engine, session_scope  # noqa: E402
from app.repositories import members as members_repo  # noqa: E402
from app.services import accounts  # noqa: E402


def unit_checks():
    h = security.hash_password("hunter2")
    assert h.startswith("$2b$") and "hunter2" not in h
    assert security.verify_password("hunter2", h)
    assert not security.verify_password("wrong", h)
    assert not security.verify_password("x", None)
    assert not security.verify_password("hunter2", "not-a-bcrypt-hash")  # malformed -> False
    print("ok bcrypt password hash/verify (not plaintext)")


async def db_checks():
    await create_all()

    async with session_scope() as session:
        await accounts.register(session, username="amit", password="secret123")
    async with session_scope() as session:
        m = await members_repo.get_by_username(session, "amit")
        assert m is not None and m.role == "guest", "new users default to guest"
        assert m.name == "amit" and m.username == "amit"
        assert m.password_hash and "secret123" not in m.password_hash
    print("ok registered member is a guest, password stored hashed")

    async with engine.connect() as conn:
        cols = {r[1] for r in (await conn.execute(text("PRAGMA table_info(members)"))).all()}
    assert {"username", "password_hash", "email", "whatsapp"} <= cols
    print("ok members table has the account/contact columns")

    async with session_scope() as session:
        m = await members_repo.get_by_username(session, "amit")
        await accounts.set_role(session, m, "tenant")
    async with session_scope() as session:
        assert (await members_repo.get_by_username(session, "amit")).role == "tenant"
    print("ok set_role promotes guest -> tenant")

    async with session_scope() as session:
        # A forged/garbage member id is a clean miss, never a TypeError/OverflowError.
        assert await members_repo.get(session, "abc") is None
        assert await members_repo.get(session, 2 ** 70) is None
    print("ok forged/out-of-range member id -> None (no crash)")

    # The lower(username) unique index is the authoritative duplicate guard.
    try:
        async with session_scope() as session:
            await members_repo.register(
                session, username="AMIT", password_hash=security.hash_password("x" * 8)
            )
        assert False, "duplicate username (case-insensitive) should hit the unique index"
    except IntegrityError:
        print("ok duplicate register rejected by lower(username) unique index")

    await dispose()


def main():
    unit_checks()
    asyncio.run(db_checks())
    print("\nAUTH SMOKE: ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
