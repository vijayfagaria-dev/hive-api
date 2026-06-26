"""Invitations — a member with INVITE_MEMBER mints a single-use link for someone
to join the household at a chosen role.

create() returns a token (the shareable link); accept() redeems it at registration,
creating the member at the invited role instead of the default guest. Pending
invites expire after a configurable window and are rate-limited per inviter.
"""

from __future__ import annotations

import secrets
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import DomainError, NotFound, Unprocessable
from app.core.sanitize import clean
from app.db.models import Invitation, Member
from app.domain import permissions
from app.domain.enums import InvitationStatus, MemberEventType, Permission, Role
from app.domain.time import deadline_iso, now, now_iso
from app.repositories import invitations as invitations_repo
from app.repositories import member_events as events_repo
from app.repositories import members as members_repo
from app.services import accounts, notifications

_VALID_ROLES = {Role.TENANT.value, Role.GUEST.value}


async def create(
    session: AsyncSession,
    *,
    actor: Member,
    role: str,
    email: Optional[str] = None,
    name: Optional[str] = None,
) -> Invitation:
    permissions.require(actor, Permission.INVITE_MEMBER)
    if role not in _VALID_ROLES:
        raise Unprocessable(f"role must be one of {sorted(_VALID_ROLES)}.")
    if settings.invite_max_per_day > 0:
        since = deadline_iso(now(), -24)
        if await invitations_repo.count_since(session, actor.id, since) >= settings.invite_max_per_day:
            raise DomainError(f"You've hit the limit of {settings.invite_max_per_day} invites in 24h.")
    return await invitations_repo.insert(
        session,
        token=secrets.token_urlsafe(24),
        role=role,
        invited_by=actor.id,
        name=clean(name, max_len=80) if name else None,
        email=(email or "").strip() or None,
        expires_at=deadline_iso(now(), settings.invite_expiry_hours),
    )


async def list_pending(session: AsyncSession) -> list[Invitation]:
    return await invitations_repo.list_pending(session)


async def preview(session: AsyncSession, token: str) -> Invitation:
    """Public, read-only look at a pending invite (for the join page)."""
    inv = await invitations_repo.get_by_token(session, token)
    if inv is None or inv.status != InvitationStatus.PENDING or now_iso() >= inv.expires_at:
        raise NotFound("That invite link is invalid or has expired.")
    return inv


async def revoke(session: AsyncSession, *, actor: Member, invitation_id: int) -> Invitation:
    permissions.require(actor, Permission.INVITE_MEMBER)
    inv = await invitations_repo.get(session, invitation_id)
    if inv is None:
        raise NotFound("No such invitation.")
    if inv.status != InvitationStatus.PENDING:
        raise DomainError("Only a pending invite can be revoked.")
    inv.status = InvitationStatus.REVOKED
    return inv


async def accept(session: AsyncSession, *, token: str, username: str, password: str) -> Member:
    """Redeem an invite during registration: create the member at the invited role."""
    inv = await invitations_repo.get_by_token(session, token)
    if inv is None:
        raise NotFound("That invite link is invalid.")
    if inv.status != InvitationStatus.PENDING:
        raise DomainError("That invite has already been used or revoked.")
    if now_iso() >= inv.expires_at:
        inv.status = InvitationStatus.EXPIRED
        raise DomainError("That invite link has expired.")

    member = await accounts.register_with_role(
        session, username=username, password=password,
        role=inv.role, name=inv.name, email=inv.email,
    )
    inv.status = InvitationStatus.ACCEPTED
    inv.accepted_by = member.id
    inv.accepted_at = now_iso()
    await events_repo.log_event(
        session, member_id=member.id, type=MemberEventType.INVITE_ACCEPTED,
        actor_id=inv.invited_by, detail=f"joined as {inv.role}",
    )
    inviter = await members_repo.get(session, inv.invited_by)
    if inviter is not None and inviter.is_active:
        await notifications.invite_accepted(session, inviter=inviter, who=member.name)
    return member
