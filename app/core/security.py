"""Security primitives — password hashing + the session cookie.

Standard building blocks, no hand-rolled crypto:
  * Passwords: bcrypt (`hashpw`/`checkpw`).
  * Sessions: Starlette's signed `request.session` cookie (installed in main.py);
    we only read/write the `member_id` key here.

Pure: no DB access (resolving the session member to a row lives in api/deps.py).
"""

from __future__ import annotations

from typing import Optional

import bcrypt
from starlette.requests import Request

_SESSION_KEY = "member_id"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, stored: Optional[str]) -> bool:
    if not stored:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def login_session(request: Request, member_id: int) -> None:
    request.session[_SESSION_KEY] = member_id


def logout_session(request: Request) -> None:
    request.session.clear()


def session_member_id(request: Request) -> Optional[int]:
    return request.session.get(_SESSION_KEY)
