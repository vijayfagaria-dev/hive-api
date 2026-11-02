"""Accounts — member creation, authentication, contact channels, passwords, sessions.

Self-registration always creates a guest; promotion to tenant is admin-only. New
web signups go through `services.verification` (email OTP) and land here via
`create_member` once the email is proven.
Input validation surfaces as Unprocessable/Conflict; the API maps them to 422/409.
"""

from __future__ import annotations

import re
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import settings
from app.core.errors import Conflict, DomainError, Forbidden, TooManyRequests, Unauthorized, Unprocessable
from app.db.models import Member
from app.domain import passwords
from app.domain.enums import Role
from app.domain.time import iso, now, now_iso, seconds_until, shift_iso
from app.repositories import members as members_repo

# E.164: optional '+', leading non-zero digit, 8–15 digits total.
_WA_RE = re.compile(r"^\+?[1-9]\d{7,14}$")
# Pragmatic shape check (one @, a dotted domain, no spaces) — the OTP proves the rest.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_whatsapp(raw: str) -> str:
    """Strip spaces/dashes/parens, validate E.164, or raise Unprocessable."""
    cleaned = re.sub(r"[\s\-()]", "", raw.strip())
    if not _WA_RE.match(cleaned):
        raise Unprocessable("WhatsApp number must be international, e.g. +919876543210.")
    return cleaned


def normalize_email(raw: Optional[str]) -> str:
    """Trim + lower-case + shape-check, or raise Unprocessable."""
    email = (raw or "").strip().lower()
    if not email:
        raise Unprocessable("Email is required.")
    if len(email) > 254 or not _EMAIL_RE.match(email):
        raise Unprocessable("That doesn't look like an email address.")
    return email


def validate_username(raw: str) -> str:
    username = raw.strip()
    if len(username) < 3:
        raise Unprocessable("Username must be at least 3 characters.")
    if len(username) > 32:
        raise Unprocessable("Username must be at most 32 characters.")
    if "@" in username:
        raise Unprocessable("Username can't contain '@'.")
    return username


def check_new_password(password: str, *, username: Optional[str] = None) -> None:
    """Enforce the password policy (app.domain.passwords) on a password being set."""
    issues = passwords.problems(password, username=username, min_length=settings.password_min_length)
    if issues:
        raise Unprocessable(issues[0])


async def create_member(
    session: AsyncSession,
    *,
    username: str,
    role: str,
    password: Optional[str] = None,
    password_hash: Optional[str] = None,
    name: Optional[str] = None,
    email: Optional[str] = None,
    whatsapp: Optional[str] = None,
    email_verified: bool = False,
) -> Member:
    """Validate + create a member at the given role. Takes a plain `password` (policy
    enforced here) or a `password_hash` already vetted when the signup started."""
    username = validate_username(username)
    if password_hash is None:
        if password is None:
            raise Unprocessable("Password is required.")
        check_new_password(password, username=username)
        password_hash = security.hash_password(password)
    if await members_repo.get_by_username(session, username) is not None:
        raise Conflict("That username is taken.")
    email_value = normalize_email(email) if email and email.strip() else None
    if email_value and await members_repo.email_in_use(session, email_value):
        raise Conflict("That email is already linked to another account.")
    try:
        member = await members_repo.create(
            session, username=username, password_hash=password_hash, role=role, name=name,
        )
    except IntegrityError:  # lower(username) unique index caught a TOCTOU race
        raise Conflict("That username is taken.")
    if email_value:
        member.email = email_value
        member.email_verified_at = now_iso() if email_verified else None
    if whatsapp and whatsapp.strip():
        member.whatsapp = normalize_whatsapp(whatsapp)
    return member


async def register(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    email: Optional[str] = None,
    whatsapp: Optional[str] = None,
) -> Member:
    """Create a guest directly (admin tooling / tests). The web signup path is
    `verification.start_registration` -> `complete_registration`."""
    return await create_member(
        session, username=username, password=password, role=Role.GUEST,
        email=email, whatsapp=whatsapp,
    )


async def authenticate(session: AsyncSession, username: str, password: str) -> Member:
    """Check credentials with brute-force protection: LOGIN_MAX_FAILURES consecutive
    misses lock the account for LOGIN_LOCKOUT_MINUTES (a password reset unlocks it).
    Counters persist even though the failed request rolls back."""
    member = await members_repo.get_by_username(session, username.strip())
    if member is None or not member.password_hash:
        security.burn_password_check(password)
        raise Unauthorized("Wrong username or password.")
    t = now()
    if member.locked_until and iso(t) < member.locked_until:
        wait = seconds_until(member.locked_until, t)
        raise TooManyRequests(
            f"Too many wrong passwords — try again in {max(1, -(-wait // 60))} min, or reset your password.",
            retry_after=wait,
        )
    if not security.verify_password(password, member.password_hash):
        member.failed_logins += 1
        if settings.login_max_failures > 0 and member.failed_logins >= settings.login_max_failures:
            member.failed_logins = 0
            member.locked_until = shift_iso(t, settings.login_lockout_minutes * 60)
            raise TooManyRequests(
                f"Too many wrong passwords — your account is locked for {settings.login_lockout_minutes} min. "
                "Reset your password to get back in sooner.",
                retry_after=settings.login_lockout_minutes * 60,
                persist=True,
            )
        raise Unauthorized("Wrong username or password.", persist=True)
    if not member.is_active:
        raise Forbidden("This account is no longer part of the household.")
    member.failed_logins = 0
    member.locked_until = None
    return member


async def set_whatsapp(session: AsyncSession, member: Member, whatsapp: Optional[str]) -> Optional[str]:
    raw = (whatsapp or "").strip()
    value = normalize_whatsapp(raw) if raw else None
    member.whatsapp = value
    return value


def _set_password(member: Member, new_password: str) -> None:
    """Store a new password, sign out every other session, and lift any lockout."""
    check_new_password(new_password, username=member.username)
    member.password_hash = security.hash_password(new_password)
    member.session_version += 1
    member.failed_logins = 0
    member.locked_until = None


async def change_password(
    session: AsyncSession, member: Member, current_password: str, new_password: str
) -> None:
    """Change the logged-in member's own password, verifying the current one first.
    Bumps the session version — the caller re-issues the current cookie.

    Wrong current password / unchanged new password raise DomainError (400) — never
    Unauthorized (401), so the member isn't bounced to login mid-change.
    """
    if not security.verify_password(current_password, member.password_hash):
        raise DomainError("Current password is incorrect.")
    if security.verify_password(new_password, member.password_hash):
        raise DomainError("New password must be different from the current one.")
    _set_password(member, new_password)


async def reset_password(session: AsyncSession, member: Member, new_password: str) -> None:
    """Set a new password without the current one — after an emailed-code reset, or
    from `app.admin` (a locked-out member has no current password to prove)."""
    _set_password(member, new_password)


async def logout_everywhere(session: AsyncSession, member: Member) -> None:
    """Invalidate every session cookie this member holds (including the caller's)."""
    member.session_version += 1


async def set_role(session: AsyncSession, member: Member, role: str) -> None:
    """Promote/demote — the only path to the tenant role (admin-only)."""
    member.role = role
