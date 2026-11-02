"""Email-verified auth flows — signup, forgot password, and email change.

Each flow is "start -> (resend) -> verify" on top of `services.otp`:

  * Signup: the registration waits on the challenge row; the member is only created
    once the code is verified, so unverified signups never appear in the roster,
    votes, or splits — and abandoned ones simply expire.
  * Forgot password: identical responses whether or not the email has an account
    (an unknown address gets a decoy challenge that mails nothing). A verified code
    is traded for a short-lived single-use reset token; redeeming it sets the
    password, signs out every session, lifts any lockout, and mails a notice.
  * Email change: the new address must prove itself before it replaces the old one
    (otherwise a hijacked session could swap in an attacker's inbox, then reset).
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import settings
from app.core.errors import Conflict, DomainError
from app.db.models import Member, OtpChallenge
from app.domain.enums import MemberEventType, OtpPurpose, Role
from app.domain.time import iso, now, now_iso, shift_iso
from app.infra import email_templates, mailer
from app.repositories import member_events as events_repo
from app.repositories import members as members_repo
from app.repositories import otp as otp_repo
from app.services import accounts, invitations, otp

logger = logging.getLogger("hive.auth")

_RESET_EXPIRED = "This reset session has expired — request a new code."


def _mail_code(session: AsyncSession, challenge: OtpChallenge, code: str, username: Optional[str]) -> None:
    mailer.send_after_commit(
        session,
        email_templates.otp_email(
            purpose=challenge.purpose, to=challenge.email, code=code,
            minutes=settings.otp_ttl_minutes, username=username,
        ),
    )


# --- Signup -----------------------------------------------------------------

async def start_registration(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    email: Optional[str],
    whatsapp: Optional[str] = None,
    invite: Optional[str] = None,
) -> OtpChallenge:
    """Validate the signup and mail a verification code. Nothing is created yet."""
    username = accounts.validate_username(username)
    email = accounts.normalize_email(email)
    accounts.check_new_password(password, username=username)
    wa = accounts.normalize_whatsapp(whatsapp) if whatsapp and whatsapp.strip() else None
    if invite:
        await invitations.redeemable(session, invite)
    if await members_repo.get_by_username(session, username) is not None:
        raise Conflict("That username is taken.")
    if await members_repo.email_in_use(session, email):
        raise Conflict("That email is already linked to an account — log in or reset your password.")
    challenge, code = await otp.issue(
        session,
        purpose=OtpPurpose.REGISTER,
        email=email,
        username=username,
        password_hash=security.hash_password(password),
        whatsapp=wa,
        invite_token=invite or None,
    )
    if code:
        _mail_code(session, challenge, code, username)
    return challenge


async def resend_registration(session: AsyncSession, email: str) -> OtpChallenge:
    email = accounts.normalize_email(email)
    challenge, code = await otp.resend(session, purpose=OtpPurpose.REGISTER, email=email)
    _mail_code(session, challenge, code, challenge.username)
    return challenge


async def complete_registration(session: AsyncSession, *, email: str, code: str) -> Member:
    """Verify the signup code and create the (email-verified) member."""
    email = accounts.normalize_email(email)
    challenge = await otp.verify(session, purpose=OtpPurpose.REGISTER, email=email, code=code)
    challenge.consumed_at = now_iso()
    inv = await invitations.redeemable(session, challenge.invite_token) if challenge.invite_token else None
    try:
        member = await accounts.create_member(
            session,
            username=challenge.username or "",
            password_hash=challenge.password_hash,
            role=inv.role if inv else Role.GUEST,
            name=inv.name if inv else None,
            email=email,
            whatsapp=challenge.whatsapp,
            email_verified=True,
        )
    except Conflict as exc:
        # Claimed by someone else while this code was in flight — the signup must restart.
        raise Conflict(f"{exc.detail} Go back and start again.")
    if inv is not None:
        await invitations.mark_accepted(session, inv, member)
    else:
        await events_repo.log_event(session, member_id=member.id, type=MemberEventType.JOINED)
    return member


# --- Forgot password --------------------------------------------------------

async def _reset_target(session: AsyncSession, email: str) -> Optional[Member]:
    """The one active, login-capable member with this email — or None (unknown, or a
    legacy duplicate we can't safely pick between)."""
    found = [m for m in await members_repo.list_active_by_email(session, email) if m.username and m.password_hash]
    if len(found) > 1:
        logger.warning("Password reset for an email shared by %d members — not sent", len(found))
        return None
    return found[0] if found else None


async def request_password_reset(session: AsyncSession, email: str) -> OtpChallenge:
    email = accounts.normalize_email(email)
    member = await _reset_target(session, email)
    challenge, code = await otp.issue(
        session,
        purpose=OtpPurpose.PASSWORD_RESET,
        email=email,
        member_id=member.id if member else None,
    )
    if code and member is not None:
        _mail_code(session, challenge, code, member.username)
    return challenge


async def resend_password_reset(session: AsyncSession, email: str) -> OtpChallenge:
    email = accounts.normalize_email(email)
    challenge, code = await otp.resend(session, purpose=OtpPurpose.PASSWORD_RESET, email=email)
    member = await members_repo.get(session, challenge.member_id) if challenge.member_id else None
    if member is not None and member.is_active:
        _mail_code(session, challenge, code, member.username)
    return challenge


async def verify_password_reset(session: AsyncSession, *, email: str, code: str) -> tuple[str, int]:
    """Trade a correct reset code for a single-use reset token. Returns (token, ttl_s)."""
    email = accounts.normalize_email(email)
    challenge = await otp.verify(session, purpose=OtpPurpose.PASSWORD_RESET, email=email, code=code)
    if challenge.member_id is None:
        # A decoy (no such account) whose random code was guessed — still a miss.
        raise DomainError("That code is incorrect.")
    token = security.generate_token()
    ttl = settings.reset_token_ttl_minutes * 60
    challenge.reset_token_hash = security.hash_token(token)
    challenge.reset_expires_at = shift_iso(now(), ttl)
    return token, ttl


async def complete_password_reset(session: AsyncSession, *, token: str, new_password: str) -> Member:
    challenge = await otp_repo.get_by_reset_token(session, security.hash_token(token or ""))
    t = now()
    if (
        challenge is None
        or challenge.consumed_at is not None
        or not challenge.reset_expires_at
        or iso(t) >= challenge.reset_expires_at
    ):
        raise DomainError(_RESET_EXPIRED)
    member = await members_repo.get(session, challenge.member_id)
    if member is None or not member.is_active:
        raise DomainError(_RESET_EXPIRED)
    await accounts.reset_password(session, member, new_password)
    challenge.consumed_at = iso(t)
    # The reset just proved this inbox belongs to the member.
    if member.email and member.email.lower() == challenge.email and member.email_verified_at is None:
        member.email_verified_at = iso(t)
    notify_password_changed(session, member, how="reset")
    return member


def notify_password_changed(session: AsyncSession, member: Member, *, how: str) -> None:
    """Security notice to the account email after a password change or reset."""
    if member.email:
        mailer.send_after_commit(
            session,
            email_templates.password_changed_email(to=member.email, username=member.username or member.name, how=how),
        )


# --- Email change -----------------------------------------------------------

async def start_email_change(session: AsyncSession, member: Member, raw_email: Optional[str]) -> Optional[OtpChallenge]:
    """Clearing the email applies at once. A new (or still-unverified) address gets a
    code and only replaces the current one after `complete_email_change`. Returns the
    pending challenge, or None when nothing is waiting."""
    if not (raw_email or "").strip():
        member.email = None
        member.email_verified_at = None
        return None
    email = accounts.normalize_email(raw_email)
    if member.email and member.email.lower() == email and member.email_verified_at:
        return None  # already this address, already verified
    if await members_repo.email_in_use(session, email, exclude_id=member.id):
        raise Conflict("That email is already linked to another account.")
    challenge, code = await otp.issue(
        session,
        purpose=OtpPurpose.CHANGE_EMAIL,
        email=email,
        member_id=member.id,
        scope_to_member=True,
    )
    if code:
        _mail_code(session, challenge, code, member.username)
    return challenge


async def resend_email_change(session: AsyncSession, member: Member, email: str) -> OtpChallenge:
    email = accounts.normalize_email(email)
    challenge, code = await otp.resend(
        session, purpose=OtpPurpose.CHANGE_EMAIL, email=email, member_id=member.id
    )
    _mail_code(session, challenge, code, member.username)
    return challenge


async def complete_email_change(session: AsyncSession, member: Member, *, email: str, code: str) -> str:
    email = accounts.normalize_email(email)
    challenge = await otp.verify(
        session, purpose=OtpPurpose.CHANGE_EMAIL, email=email, code=code, member_id=member.id
    )
    challenge.consumed_at = now_iso()
    if await members_repo.email_in_use(session, email, exclude_id=member.id):
        raise Conflict("That email is already linked to another account.")
    member.email = email
    member.email_verified_at = now_iso()
    return email
