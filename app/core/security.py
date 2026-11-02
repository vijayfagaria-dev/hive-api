"""Security primitives — password hashing, one-time codes, and the session cookie.

Standard building blocks, no hand-rolled crypto:
  * Passwords: bcrypt (`hashpw`/`checkpw`).
  * One-time codes + reset tokens: CSPRNG (`secrets`) and keyed HMAC-SHA256 digests,
    so a leaked database alone can't be used to brute-force a 6-digit code.
  * Sessions: Starlette's signed `request.session` cookie (installed in main.py);
    we read/write the `member_id` + `sv` (session version) keys here.

Pure: no DB access (resolving the session member to a row lives in api/deps.py).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Optional

import bcrypt
from starlette.requests import Request

from app.core.config import settings

_SESSION_KEY = "member_id"
_VERSION_KEY = "sv"

OTP_DIGITS = 6

# Checked against when the username doesn't exist, so a miss costs the same bcrypt
# time as a hit (no username enumeration by response timing).
_DUMMY_HASH = bcrypt.hashpw(b"hive-timing-equalizer", bcrypt.gensalt()).decode("utf-8")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, stored: Optional[str]) -> bool:
    if not stored:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def burn_password_check(password: str) -> None:
    """Spend one bcrypt check on a throwaway hash (timing parity for unknown users)."""
    verify_password(password, _DUMMY_HASH)


# --- One-time codes + opaque tokens -----------------------------------------

def _hmac(message: str) -> str:
    return hmac.new(settings.secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def generate_otp() -> str:
    return f"{secrets.randbelow(10 ** OTP_DIGITS):0{OTP_DIGITS}d}"


def hash_otp(purpose: str, email: str, code: str) -> str:
    """Digest bound to purpose + address, so a code can't be replayed in another flow."""
    return _hmac(f"otp:{purpose}:{email}:{code}")


def verify_otp(purpose: str, email: str, code: str, stored: str) -> bool:
    return hmac.compare_digest(hash_otp(purpose, email, code), stored)


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return _hmac(f"token:{token}")


# --- Session cookie ----------------------------------------------------------

def login_session(request: Request, member_id: int, session_version: int = 0) -> None:
    # Start from a clean cookie on every login — nothing from a previous identity survives.
    request.session.clear()
    request.session[_SESSION_KEY] = member_id
    request.session[_VERSION_KEY] = session_version


def logout_session(request: Request) -> None:
    request.session.clear()


def session_member_id(request: Request) -> Optional[int]:
    return request.session.get(_SESSION_KEY)


def session_version(request: Request) -> int:
    """Cookies minted before session versioning carry no `sv` — they count as version 0,
    so existing logins survive the upgrade until the member's version is bumped."""
    value = request.session.get(_VERSION_KEY, 0)
    return value if isinstance(value, int) else -1
