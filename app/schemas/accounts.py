"""Auth / account contracts."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class Credentials(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    # Optional contact channels; used on register, ignored on login.
    email: Optional[str] = Field(default=None, max_length=254)
    whatsapp: Optional[str] = Field(default=None, max_length=24)
    # Optional invite token; on register, redeems the invite (joins at its role).
    invite: Optional[str] = Field(default=None, max_length=128)


class EmailBody(BaseModel):
    email: Optional[str] = Field(default=None, max_length=254)


class WhatsappBody(BaseModel):
    whatsapp: Optional[str] = Field(default=None, max_length=24)


class PasswordChangeBody(BaseModel):
    currentPassword: str = Field(min_length=1)
    newPassword: str = Field(min_length=1, max_length=128)


def member_out(member) -> Optional[dict]:
    """Public-safe view (no contact details) — for OTHER members in lists/detail."""
    if member is None:
        return None
    return {
        "id": member.id,
        "name": member.name,
        "username": member.username,
        "role": member.role,
    }


def self_out(member) -> Optional[dict]:
    """The logged-in member's own view — adds private contact fields."""
    if member is None:
        return None
    return {**member_out(member), "email": member.email, "whatsapp": member.whatsapp}
