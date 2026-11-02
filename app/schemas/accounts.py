"""Auth / account contracts."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    # Contact channels; email is required on register (it gets verified), ignored on login.
    email: Optional[str] = Field(default=None, max_length=254)
    whatsapp: Optional[str] = Field(default=None, max_length=24)
    # Optional invite token; on register, redeems the invite (joins at its role).
    invite: Optional[str] = Field(default=None, max_length=128)


class EmailOnly(BaseModel):
    email: str = Field(min_length=1, max_length=254)


class EmailCode(BaseModel):
    email: str = Field(min_length=1, max_length=254)
    code: str = Field(min_length=1, max_length=16)


class PasswordResetBody(BaseModel):
    resetToken: str = Field(min_length=1, max_length=128)
    newPassword: str = Field(min_length=1, max_length=256)


class EmailBody(BaseModel):
    email: Optional[str] = Field(default=None, max_length=254)


class WhatsappBody(BaseModel):
    whatsapp: Optional[str] = Field(default=None, max_length=24)


class PasswordChangeBody(BaseModel):
    currentPassword: str = Field(min_length=1, max_length=256)
    newPassword: str = Field(min_length=1, max_length=256)


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
    return {
        **member_out(member),
        "email": member.email,
        "emailVerified": bool(member.email and member.email_verified_at),
        "whatsapp": member.whatsapp,
    }


def challenge_out(challenge, timers: dict) -> dict:
    """A code is on its way: where (signup/email change echo the address the user
    typed) and the countdowns for the OTP screen."""
    return {"email": challenge.email, **timers}
