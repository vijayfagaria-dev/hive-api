"""Accounts — registration, authentication, contact channels, role changes.

Self-registration always creates a guest; promotion to tenant is admin-only.
Input validation surfaces as Unprocessable/Conflict; the API maps them to 422/409.
"""

from __future__ import annotations

import re
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, Unauthorized, Unprocessable
from app.core.security import hash_password, verify_password
from app.db.models import Member
from app.domain.enums import Role
from app.repositories import members as members_repo

# E.164: optional '+', leading non-zero digit, 8–15 digits total.
_WA_RE = re.compile(r"^\+?[1-9]\d{7,14}$")


def normalize_whatsapp(raw: str) -> str:
    """Strip spaces/dashes/parens, validate E.164, or raise Unprocessable."""
    cleaned = re.sub(r"[\s\-()]", "", raw.strip())
    if not _WA_RE.match(cleaned):
        raise Unprocessable("WhatsApp number must be international, e.g. +919876543210.")
    return cleaned


def _validate_email(email: str) -> str:
    if "@" not in email or "." not in email.split("@")[-1]:
        raise Unprocessable("That doesn't look like an email address.")
    return email


async def register(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    email: Optional[str] = None,
    whatsapp: Optional[str] = None,
) -> Member:
    username = username.strip()
    if len(username) < 3:
        raise Unprocessable("Username must be at least 3 characters.")
    if len(password) < 6:
        raise Unprocessable("Password must be at least 6 characters.")
    if await members_repo.get_by_username(session, username) is not None:
        raise Conflict("That username is taken.")
    try:
        member = await members_repo.register(
            session, username=username, password_hash=hash_password(password)
        )
    except IntegrityError:  # lower(username) unique index caught a TOCTOU race
        raise Conflict("That username is taken.")
    if email and email.strip():
        member.email = _validate_email(email.strip())
    if whatsapp and whatsapp.strip():
        member.whatsapp = normalize_whatsapp(whatsapp)
    return member


async def authenticate(session: AsyncSession, username: str, password: str) -> Member:
    member = await members_repo.get_by_username(session, username.strip())
    if member is None or not verify_password(password, member.password_hash):
        raise Unauthorized("Wrong username or password.")
    return member


async def set_email(session: AsyncSession, member: Member, email: Optional[str]) -> Optional[str]:
    value = (email or "").strip() or None
    if value is not None:
        value = _validate_email(value)
    member.email = value
    return value


async def set_whatsapp(session: AsyncSession, member: Member, whatsapp: Optional[str]) -> Optional[str]:
    raw = (whatsapp or "").strip()
    value = normalize_whatsapp(raw) if raw else None
    member.whatsapp = value
    return value


async def set_role(session: AsyncSession, member: Member, role: str) -> None:
    """Promote/demote — the only path to the tenant role (admin-only)."""
    member.role = role
