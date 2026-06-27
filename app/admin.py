"""Tiny admin CLI — promote/demote/list members.

    python -m app.admin list
    python -m app.admin promote <username>     # guest -> tenant
    python -m app.admin demote  <username>     # tenant -> guest
    python -m app.admin reset-rules            # apply the house-rules seed to this DB

The manual "make them a tenant" step — there is no self-service path to tenant.
"""

from __future__ import annotations

import asyncio
import sys

from app.db.seed import STARTER_RULES, converge_rules
from app.db.session import create_all, dispose, session_scope
from app.domain.enums import Role
from app.repositories import members as members_repo
from app.services import accounts


async def _set_role(username: str, role: str) -> None:
    await create_all()
    async with session_scope() as session:
        member = await members_repo.get_by_username(session, username)
        if member is None:
            print(f"No member with username {username!r}.")
            return
        await accounts.set_role(session, member, role)
        print(f"{member.username} (id {member.id}) is now a {role}.")
    await dispose()


async def _list() -> None:
    await create_all()
    async with session_scope() as session:
        members = await members_repo.list_active(session)
        if not members:
            print("(no members yet)")
        for m in members:
            login = m.username or "(no login)"
            print(f"  {m.id:>3}  {m.role:<7}  {login:<16}  {m.name}")
    await dispose()


async def _reset_rules() -> None:
    """Apply the house-rules seed to this DB (idempotent, FK-safe)."""
    await create_all()
    async with session_scope() as session:
        added, deactivated = await converge_rules(session)
    print(f"rules: +{added} added, -{deactivated} deactivated, {len(STARTER_RULES)} active total.")
    await dispose()


def main(argv: list[str]) -> None:
    if len(argv) >= 3 and argv[1] in ("promote", "demote"):
        role = Role.TENANT if argv[1] == "promote" else Role.GUEST
        asyncio.run(_set_role(argv[2], role))
    elif len(argv) >= 2 and argv[1] == "list":
        asyncio.run(_list())
    elif len(argv) >= 2 and argv[1] == "reset-rules":
        asyncio.run(_reset_rules())
    else:
        print("usage: python -m app.admin [ list | promote <username> | demote <username> | reset-rules ]")


if __name__ == "__main__":
    main(sys.argv)
