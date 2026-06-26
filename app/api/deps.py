"""Shared FastAPI dependencies: the request-scoped session and the auth chain.

`get_session` is FastAPI-cached per request, so the auth dependencies and the
route share one session (one transactional unit of work, committed on success).
Auth failures raise semantic errors mapped to 401/403 by the exception handler.
"""

from __future__ import annotations

from typing import Optional

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.core import security
from app.core.errors import Forbidden, Unauthorized
from app.db.models import Member
from app.db.session import get_session
from app.domain import permissions
from app.domain.enums import Permission, Role
from app.repositories import members as members_repo

__all__ = [
    "get_session",
    "current_member",
    "require_login",
    "require_tenant",
    "require_permission",
]


async def current_member(
    request: Request, session: AsyncSession = Depends(get_session)
) -> Optional[Member]:
    """The logged-in active member, or None (for role-aware public endpoints)."""
    member_id = security.session_member_id(request)
    if member_id is None:
        return None
    member = await members_repo.get(session, member_id)
    if member is None or not member.is_active:
        return None
    return member


async def require_login(member: Optional[Member] = Depends(current_member)) -> Member:
    if member is None:
        raise Unauthorized("Not logged in.")
    return member


async def require_tenant(member: Member = Depends(require_login)) -> Member:
    if member.role != Role.TENANT:
        raise Forbidden("Tenants only.")
    return member


def require_permission(permission: Permission):
    """Dependency factory: require the logged-in member to hold `permission`.

    Prefer this over `require_tenant` for new endpoints — it checks a capability,
    not a role, so future roles need no route changes (see app.domain.permissions).
    """

    async def _dep(member: Member = Depends(require_login)) -> Member:
        permissions.require(member, permission)
        return member

    return _dep
