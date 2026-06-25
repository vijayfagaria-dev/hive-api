"""Tiny admin CLI — promote/demote/list members.

    python -m app.admin list
    python -m app.admin promote <username>     # guest -> tenant
    python -m app.admin demote  <username>     # tenant -> guest

This is the manual "make them a tenant" step — there is no self-service path to
the tenant role (BR-A03).
"""

from __future__ import annotations

import asyncio
import sys

from . import db as dbm
from . import queries


async def _set_role(username: str, role: str) -> None:
    db = await dbm.connect()
    try:
        member = await queries.get_member_by_username(db, username)
        if member is None:
            print(f"No member with username {username!r}.")
            return
        await queries.set_role(db, member["id"], role)
        print(f"{member['username']} (id {member['id']}) is now a {role}.")
    finally:
        await db.close()


async def _list() -> None:
    db = await dbm.connect()
    try:
        members = await queries.list_active_members(db)
        if not members:
            print("(no members yet)")
        for m in members:
            login = m["username"] or "(bot-only)"
            print(f"  {m['id']:>3}  {m['role']:<7}  {login:<16}  {m['name']}")
    finally:
        await db.close()


def main(argv: list[str]) -> None:
    if len(argv) >= 3 and argv[1] in ("promote", "demote"):
        asyncio.run(_set_role(argv[2], "tenant" if argv[1] == "promote" else "guest"))
    elif len(argv) >= 2 and argv[1] == "list":
        asyncio.run(_list())
    else:
        print("usage: python -m app.admin [ list | promote <username> | demote <username> ]")


if __name__ == "__main__":
    main(sys.argv)
