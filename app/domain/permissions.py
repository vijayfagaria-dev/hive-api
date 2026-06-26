"""Role → permission policy — the one place that maps roles to capabilities.

Authorization throughout the app asks "does this member hold Permission.X?", never
"is this member a tenant?". That keeps permissions independent of roles: adding a
future role (Owner, Moderator, Read-only, House Manager) is a one-line edit to
ROLE_PERMISSIONS, with zero changes at the call sites. A future per-member override
table can layer on top of `permissions_for` without touching callers either.

Today every tenant is a full admin (holds every permission) and guests may only
view the roster — which matches the current behaviour (guests already see members
via /me), so nothing existing changes.
"""

from __future__ import annotations

from typing import Optional

from app.core.errors import Forbidden
from app.db.models import Member
from app.domain.enums import Permission, Role

# The policy. Keyed by role value; StrEnum members compare/hash as their string,
# so a member's `role` (a plain str) looks up cleanly.
ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    Role.TENANT: frozenset(Permission),  # every tenant is an admin (for now)
    Role.GUEST: frozenset({Permission.VIEW_MEMBERS}),
}

# Roles that can manage users — used to guard the last admin from removal/demotion.
ADMIN_ROLES: frozenset[str] = frozenset(
    role for role, perms in ROLE_PERMISSIONS.items() if Permission.MANAGE_USERS in perms
)


def permissions_for(member: Optional[Member]) -> frozenset[Permission]:
    """The effective permissions of a member (none if logged-out or inactive)."""
    if member is None or not member.is_active:
        return frozenset()
    return ROLE_PERMISSIONS.get(member.role, frozenset())


def has(member: Optional[Member], permission: Permission) -> bool:
    return permission in permissions_for(member)


def require(member: Optional[Member], permission: Permission) -> None:
    """Raise Forbidden (403) unless the member holds the permission."""
    if not has(member, permission):
        raise Forbidden("You don't have permission to do that.")


def can_manage_users(role: str) -> bool:
    """Whether a role grants user-management (i.e. counts as an admin)."""
    return Permission.MANAGE_USERS in ROLE_PERMISSIONS.get(role, frozenset())
