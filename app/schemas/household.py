"""Household user-management contracts — request bodies + response mappers."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class RoleBody(BaseModel):
    role: str = Field(min_length=1)


class InviteBody(BaseModel):
    role: str = Field(min_length=1)
    email: Optional[str] = Field(default=None, max_length=254)
    name: Optional[str] = Field(default=None, max_length=80)


class MemberPatch(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class RentSharesBody(BaseModel):
    # { memberId: percent } for every active tenant; must total 100.
    shares: dict[int, int]


def member_admin_out(member) -> dict:
    """Management view of a member — adds lifecycle fields, no private contacts."""
    return {
        "id": member.id,
        "name": member.name,
        "username": member.username,
        "role": member.role,
        "isActive": bool(member.is_active),
        "joinedOn": member.joined_on,
        "leftOn": member.left_on,
        "rentSharePct": member.rent_share_pct,
    }


def invitation_out(inv, *, include_token: bool = False) -> dict:
    out = {
        "id": inv.id,
        "role": inv.role,
        "name": inv.name,
        "email": inv.email,
        "status": inv.status,
        "invitedBy": inv.invited_by,
        "createdAt": inv.created_at,
        "expiresAt": inv.expires_at,
        "acceptedBy": inv.accepted_by,
        "acceptedAt": inv.accepted_at,
    }
    if include_token:  # only echoed to the inviter, right after creation
        out["token"] = inv.token
    return out


def member_event_out(ev) -> dict:
    return {
        "type": ev.type,
        "actorId": ev.actor_id,
        "detail": ev.detail,
        "oldValue": ev.old_value,
        "newValue": ev.new_value,
        "ts": ev.ts,
    }
