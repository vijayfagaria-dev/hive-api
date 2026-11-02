"""One-time email codes — the shared engine behind signup, reset, and email change.

Guarantees, for every flow:
  * Codes come from a CSPRNG and are stored only as keyed digests.
  * Expiry (OTP_TTL_MINUTES), one-time use (`consumed_at`), and at most
    OTP_MAX_ATTEMPTS wrong guesses per code; wrong guesses persist even though the
    request fails (`persist=True`).
  * Resends obey a cooldown and an hourly per-address cap (anti mail-bombing); a
    resend rotates the code, so an old code dies the moment a new one is sent.
  * Starting a flow again inside the cooldown reuses the live challenge instead of
    mailing another code (`issue` returns code=None) — double-submits stay quiet.

Callers decide what to mail and what a verified challenge unlocks.
"""

from __future__ import annotations

import re
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import settings
from app.core.errors import DomainError, TooManyRequests
from app.db.models import OtpChallenge
from app.domain.time import iso, now, parse_iso, seconds_until, shift_iso
from app.repositories import otp as otp_repo

_CODE_RE = re.compile(r"^\d{%d}$" % security.OTP_DIGITS)
_NO_CODE = "That code is invalid or has expired — request a new one."


def _ttl() -> int:
    return settings.otp_ttl_minutes * 60


def timers(challenge: OtpChallenge) -> dict:
    """Seconds left on the code and on the resend cooldown — for the UI countdowns
    (relative, so the client's clock skew doesn't matter)."""
    t = now()
    resend_at = shift_iso(parse_iso(challenge.last_sent_at), settings.otp_resend_cooldown_seconds)
    return {
        "expiresIn": seconds_until(challenge.expires_at, t),
        "resendIn": seconds_until(resend_at, t),
    }


async def _check_hourly_cap(session: AsyncSession, purpose: str, email: str) -> None:
    if settings.otp_max_sends_per_hour <= 0:
        return
    since = shift_iso(now(), -3600)
    if await otp_repo.sends_since(session, purpose, email, since) >= settings.otp_max_sends_per_hour:
        raise TooManyRequests("Too many codes requested for this email — try again in an hour.", retry_after=3600)


async def issue(
    session: AsyncSession,
    *,
    purpose: str,
    email: str,
    member_id: Optional[int] = None,
    scope_to_member: bool = False,
    **fields,
) -> tuple[OtpChallenge, Optional[str]]:
    """Start (or restart) a challenge. Returns (challenge, code-to-mail | None).

    Inside the resend cooldown the live challenge is reused (its pending fields
    refreshed) and no new code is minted. Otherwise older open challenges for the
    same flow are superseded and a fresh code is issued."""
    t = now()
    scope = member_id if scope_to_member else None
    live = await otp_repo.latest_open(session, purpose, email, scope)
    if (
        live is not None
        and live.verified_at is None
        and iso(t) < live.expires_at
        and timers(live)["resendIn"] > 0
    ):
        live.member_id = member_id
        for key, value in fields.items():
            setattr(live, key, value)
        return live, None

    await _check_hourly_cap(session, purpose, email)
    for stale in await otp_repo.list_open(session, purpose, email, scope):
        stale.consumed_at = iso(t)  # superseded
    code = security.generate_otp()
    challenge = await otp_repo.insert(
        session,
        purpose=purpose,
        email=email,
        member_id=member_id,
        code_hash=security.hash_otp(purpose, email, code),
        created_at=iso(t),
        last_sent_at=iso(t),
        expires_at=shift_iso(t, _ttl()),
        **fields,
    )
    return challenge, code


async def resend(
    session: AsyncSession, *, purpose: str, email: str, member_id: Optional[int] = None
) -> tuple[OtpChallenge, str]:
    """Rotate the code on the pending challenge (fresh expiry + attempts)."""
    challenge = await otp_repo.latest_open(session, purpose, email, member_id)
    if challenge is None or challenge.verified_at is not None:
        raise DomainError("There's no pending code for that email — start over.")
    wait = timers(challenge)["resendIn"]
    if wait > 0:
        raise TooManyRequests(f"Hang on — you can request a new code in {wait}s.", retry_after=wait)
    await _check_hourly_cap(session, purpose, email)
    t = now()
    code = security.generate_otp()
    challenge.code_hash = security.hash_otp(purpose, email, code)
    challenge.attempts = 0
    challenge.send_count += 1
    challenge.last_sent_at = iso(t)
    challenge.expires_at = shift_iso(t, _ttl())
    return challenge, code


def normalize_code(raw: str) -> str:
    code = re.sub(r"[\s-]", "", raw or "")
    if not _CODE_RE.match(code):
        raise DomainError(f"Enter the {security.OTP_DIGITS}-digit code from the email.")
    return code


async def verify(
    session: AsyncSession, *, purpose: str, email: str, code: str, member_id: Optional[int] = None
) -> OtpChallenge:
    """Check a code. Success marks the challenge verified (the caller consumes it);
    a wrong guess is counted and persisted before the error goes out."""
    code = normalize_code(code)
    challenge = await otp_repo.latest_open(session, purpose, email, member_id)
    if challenge is None or challenge.verified_at is not None:
        raise DomainError(_NO_CODE)
    if challenge.attempts >= settings.otp_max_attempts:
        raise TooManyRequests("Too many wrong codes — request a new one.")
    t = now()
    if iso(t) >= challenge.expires_at:
        raise DomainError("That code has expired — request a new one.")
    if not security.verify_otp(purpose, email, code, challenge.code_hash):
        challenge.attempts += 1
        left = settings.otp_max_attempts - challenge.attempts
        if left <= 0:
            raise TooManyRequests("Too many wrong codes — request a new one.", persist=True)
        plural = "attempt" if left == 1 else "attempts"
        raise DomainError(f"That code is incorrect — {left} {plural} left.", persist=True)
    challenge.verified_at = iso(t)
    return challenge


async def purge(session: AsyncSession) -> int:
    """Housekeeping for the sweep: drop challenges dead for over a day."""
    return await otp_repo.purge_stale(session, shift_iso(now(), -24 * 3600))
