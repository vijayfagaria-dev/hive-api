"""Household user management — list/inspect members, change roles, remove members.

Business rules live here; routes only do authorization (require_permission) + I/O.
Authorization is permission-based (app.domain.permissions): each mutation also
re-asserts the actor's Permission (defence in depth). The single invariant guard
is the **last-admin lockout** — the final member who can manage users can't be
removed or demoted. Every change is audited (member_events) and the target is
notified through the existing channels.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError, NotFound, Unprocessable
from app.core.sanitize import clean
from app.db.models import Member
from app.domain import permissions
from app.domain.enums import MemberEventType, Permission, Role
from app.domain.time import now_iso
from app.repositories import member_events as events_repo
from app.repositories import members as members_repo
from app.services import notifications

_VALID_ROLES = {Role.TENANT.value, Role.GUEST.value}


async def list_members(session: AsyncSession, *, include_inactive: bool = False) -> list[Member]:
    return await members_repo.list_all(session, include_inactive=include_inactive)


async def get_member(session: AsyncSession, member_id: int) -> Member:
    """Fetch a member for the admin detail view (active or not)."""
    target = await members_repo.get(session, member_id)
    if target is None:
        raise NotFound("No such member.")
    return target


async def _load_active(session: AsyncSession, member_id: int) -> Member:
    target = await members_repo.get(session, member_id)
    if target is None or not target.is_active:
        raise NotFound("No such member.")
    return target


async def _is_last_admin(session: AsyncSession, target: Member) -> bool:
    """True if the target is currently the only active member who can manage users."""
    if not permissions.can_manage_users(target.role):
        return False
    remaining = await members_repo.count_active_with_roles(session, permissions.ADMIN_ROLES)
    return remaining <= 1


async def change_role(session: AsyncSession, *, actor: Member, member_id: int, role: str) -> Member:
    permissions.require(actor, Permission.UPDATE_ROLE)
    if role not in _VALID_ROLES:
        raise Unprocessable(f"role must be one of {sorted(_VALID_ROLES)}.")
    target = await _load_active(session, member_id)
    old = target.role
    if old == role:
        return target  # no-op
    # Last-admin lockout: don't demote the final admin out of an admin role.
    if permissions.can_manage_users(old) and not permissions.can_manage_users(role):
        if await _is_last_admin(session, target):
            raise DomainError("Can't demote the last admin — promote someone else first.")
    target.role = role
    await events_repo.log_event(
        session, member_id=target.id, type=MemberEventType.ROLE_CHANGED,
        actor_id=actor.id, old_value=old, new_value=role,
    )
    await notifications.member_role_changed(session, member=target, by=actor.name, role=role)
    return target


async def remove(session: AsyncSession, *, actor: Member, member_id: int) -> Member:
    permissions.require(actor, Permission.REMOVE_MEMBER)
    target = await _load_active(session, member_id)
    # Last-admin lockout: the final admin can't be removed.
    if await _is_last_admin(session, target):
        raise DomainError("Can't remove the last admin — promote someone else first.")
    target.is_active = False
    target.left_on = now_iso()
    await events_repo.log_event(
        session, member_id=target.id, type=MemberEventType.REMOVED, actor_id=actor.id,
    )
    await notifications.member_removed(session, member=target, by=actor.name)
    return target


async def set_rent_shares(session: AsyncSession, *, actor: Member, shares: dict[int, int]) -> list[Member]:
    """Set the rent split % for the active tenants. Requires a share for every active
    tenant (and only them), each 0–100, totalling exactly 100. Admin only."""
    permissions.require(actor, Permission.MANAGE_USERS)
    tenants = await members_repo.list_active_tenants(session)
    tenant_ids = {t.id for t in tenants}
    if set(shares) != tenant_ids:
        raise Unprocessable("Provide a rent share for every active tenant (and only them).")
    if any(not (0 <= v <= 100) for v in shares.values()):
        raise Unprocessable("Each rent share must be between 0 and 100.")
    if sum(shares.values()) != 100:
        raise Unprocessable(f"Rent shares must total 100% (got {sum(shares.values())}%).")
    for tenant in tenants:
        tenant.rent_share_pct = shares[tenant.id]
    return tenants


async def rename(session: AsyncSession, *, actor: Member, member_id: int, name: str) -> Member:
    permissions.require(actor, Permission.MANAGE_USERS)
    cleaned = clean(name, max_len=80)
    if not cleaned:
        raise Unprocessable("Name can't be empty.")
    target = await _load_active(session, member_id)
    old = target.name
    if old == cleaned:
        return target
    target.name = cleaned
    await events_repo.log_event(
        session, member_id=target.id, type=MemberEventType.RENAMED,
        actor_id=actor.id, old_value=old, new_value=cleaned,
    )
    return target
