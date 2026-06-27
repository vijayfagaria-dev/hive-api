"""Change-password smoke test — service-level.

    .venv/bin/python3 tests/smoke_password.py
"""

import asyncio
import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_PATH"] = os.path.join(tempfile.gettempdir(), f"hive_pwd_{uuid.uuid4().hex}.db")

from app.core.errors import DomainError, Unauthorized, Unprocessable  # noqa: E402
from app.db.session import create_all, dispose, session_scope  # noqa: E402
from app.services import accounts  # noqa: E402


async def main():
    await create_all()
    try:
        async with session_scope() as s:
            m = await accounts.register(s, username="vijay", password="abc123", email=None)
        mid = m.id

        # wrong current password -> DomainError (NOT Unauthorized, so no logout)
        async with session_scope() as s:
            m = await accounts.authenticate(s, "vijay", "abc123")
            try:
                await accounts.change_password(s, m, "wrongpass", "newpass1")
                assert False
            except DomainError as e:
                assert "incorrect" in str(e).lower()
        print("ok wrong current password rejected (400, not 401)")

        # too-short new password -> Unprocessable
        async with session_scope() as s:
            m = await accounts.authenticate(s, "vijay", "abc123")
            try:
                await accounts.change_password(s, m, "abc123", "123")
                assert False
            except Unprocessable:
                pass
        print("ok short new password rejected")

        # same as current -> DomainError
        async with session_scope() as s:
            m = await accounts.authenticate(s, "vijay", "abc123")
            try:
                await accounts.change_password(s, m, "abc123", "abc123")
                assert False
            except DomainError:
                pass
        print("ok unchanged password rejected")

        # happy path: change, then old fails + new works
        async with session_scope() as s:
            m = await accounts.authenticate(s, "vijay", "abc123")
            await accounts.change_password(s, m, "abc123", "supersecret9")
        async with session_scope() as s:
            try:
                await accounts.authenticate(s, "vijay", "abc123")
                assert False
            except Unauthorized:
                pass
            again = await accounts.authenticate(s, "vijay", "supersecret9")
            assert again.id == mid
        print("ok password changed: old rejected, new accepted")

        print("\nPASSWORD SMOKE: ALL CHECKS PASSED")
    finally:
        await dispose()


if __name__ == "__main__":
    asyncio.run(main())
