"""Web auth — standard, production-grade building blocks (no hand-rolled crypto).

  * Passwords: `bcrypt` (`hashpw`/`checkpw`) — the universal password hash.
  * Sessions: Starlette's `SessionMiddleware` signed cookie, accessed via
    `request.session` (installed in app/main.py). We just read/write `member_id`.
"""

from __future__ import annotations

from typing import Optional

import bcrypt
from fastapi import Request
from fastapi.exceptions import HTTPException

from . import queries


# --- Passwords (bcrypt) ----------------------------------------------------

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, stored: Optional[str]) -> bool:
    if not stored:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# --- Sessions (Starlette SessionMiddleware via request.session) ------------

def login_member(request: Request, member_id: int) -> None:
    request.session["member_id"] = member_id


def logout_member(request: Request) -> None:
    request.session.clear()


# --- FastAPI dependencies --------------------------------------------------

async def current_member(request: Request):
    """The logged-in member (active), or None. Use directly for role-aware pages."""
    member_id = request.session.get("member_id")
    if member_id is None:
        return None
    member = await queries.get_member(request.app.state.db, member_id)
    if member is None or not member["is_active"]:
        return None
    return member


async def require_login(request: Request):
    """Logged-in member, or a 303 redirect to /login."""
    member = await current_member(request)
    if member is None:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return member


async def require_tenant(request: Request):
    """Logged-in tenant, or redirect: not logged in → /login, a guest → /me."""
    member = await require_login(request)
    if member["role"] != "tenant":
        raise HTTPException(status_code=303, headers={"Location": "/me"})
    return member
