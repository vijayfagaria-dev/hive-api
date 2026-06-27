"""Household user management — list/inspect members, change roles, remove members,
and invitations.

Authorization is permission-based: each route gates on a Permission via
require_permission(...), never on a role literal. Business rules + audit +
notifications live in the services (members, invitations).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_permission
from app.domain import permissions
from app.domain.enums import Permission
from app.repositories import member_events as events_repo
from app.schemas.household import (
    InviteBody,
    MemberPatch,
    RentSharesBody,
    RoleBody,
    invitation_out,
    member_admin_out,
    member_event_out,
)
from app.services import invitations
from app.services import members as members_svc

router = APIRouter(prefix="/household", tags=["household"])


@router.post("/rent-shares")
async def set_rent_shares(
    body: RentSharesBody,
    session: AsyncSession = Depends(get_session),
    member=Depends(require_permission(Permission.MANAGE_USERS)),
):
    """Set the rent split % for every active tenant (must total 100%). Admin only."""
    tenants = await members_svc.set_rent_shares(session, actor=member, shares=body.shares)
    return {"ok": True, "members": [member_admin_out(m) for m in tenants]}


# --- Members ---------------------------------------------------------------

@router.get("/members")
async def list_members(
    includeInactive: bool = False,
    session: AsyncSession = Depends(get_session),
    member=Depends(require_permission(Permission.VIEW_MEMBERS)),
):
    # Only managers may see members who have left.
    include = includeInactive and permissions.has(member, Permission.MANAGE_USERS)
    rows = await members_svc.list_members(session, include_inactive=include)
    return {"members": [member_admin_out(m) for m in rows]}


@router.get("/members/{member_id}")
async def get_member(
    member_id: int,
    session: AsyncSession = Depends(get_session),
    member=Depends(require_permission(Permission.VIEW_MEMBERS)),
):
    target = await members_svc.get_member(session, member_id)
    out = {"member": member_admin_out(target)}
    # The audit trail is for managers only.
    if permissions.has(member, Permission.MANAGE_USERS):
        events = await events_repo.list_for(session, member_id)
        out["events"] = [member_event_out(e) for e in events]
    return out


@router.patch("/members/{member_id}")
async def patch_member(
    member_id: int,
    body: MemberPatch,
    session: AsyncSession = Depends(get_session),
    member=Depends(require_permission(Permission.MANAGE_USERS)),
):
    target = await members_svc.rename(session, actor=member, member_id=member_id, name=body.name)
    return {"ok": True, "member": member_admin_out(target)}


@router.post("/members/{member_id}/role")
async def set_role(
    member_id: int,
    body: RoleBody,
    session: AsyncSession = Depends(get_session),
    member=Depends(require_permission(Permission.UPDATE_ROLE)),
):
    target = await members_svc.change_role(session, actor=member, member_id=member_id, role=body.role)
    return {"ok": True, "member": member_admin_out(target)}


@router.delete("/members/{member_id}")
async def remove_member(
    member_id: int,
    session: AsyncSession = Depends(get_session),
    member=Depends(require_permission(Permission.REMOVE_MEMBER)),
):
    target = await members_svc.remove(session, actor=member, member_id=member_id)
    return {"ok": True, "member": member_admin_out(target)}


# --- Invitations -----------------------------------------------------------

@router.post("/members/invite")
async def invite_member(
    body: InviteBody,
    session: AsyncSession = Depends(get_session),
    member=Depends(require_permission(Permission.INVITE_MEMBER)),
):
    inv = await invitations.create(
        session, actor=member, role=body.role, email=body.email, name=body.name
    )
    return {"ok": True, "invitation": invitation_out(inv, include_token=True)}


@router.get("/invites")
async def list_invites(
    session: AsyncSession = Depends(get_session),
    member=Depends(require_permission(Permission.INVITE_MEMBER)),
):
    rows = await invitations.list_pending(session)
    return {"invitations": [invitation_out(i) for i in rows]}


@router.post("/invites/{invitation_id}/revoke")
async def revoke_invite(
    invitation_id: int,
    session: AsyncSession = Depends(get_session),
    member=Depends(require_permission(Permission.INVITE_MEMBER)),
):
    inv = await invitations.revoke(session, actor=member, invitation_id=invitation_id)
    return {"ok": True, "invitation": invitation_out(inv)}


@router.get("/invites/{token}")
async def preview_invite(token: str, session: AsyncSession = Depends(get_session)):
    """Public preview of a pending invite, for the join page (no auth, no token echo)."""
    inv = await invitations.preview(session, token)
    inviter = await members_svc.get_member(session, inv.invited_by)
    return {
        "role": inv.role,
        "name": inv.name,
        "invitedBy": inviter.name if inviter else None,
        "expiresAt": inv.expires_at,
    }
