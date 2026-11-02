"""Auth routes — login / logout / me, email-verified signup, and forgot password.

Signup:  POST /register -> code mailed -> POST /register/verify (creates + logs in)
Reset:   POST /password/forgot -> POST /password/verify (-> resetToken)
         -> POST /password/reset (sets password, signs out everywhere, logs in)
Both have a /resend. Public endpoints are throttled per client IP on top of the
per-account limits enforced in the services.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.api.deps import current_member, get_session, require_login
from app.core import ratelimit, security
from app.schemas.accounts import (
    Credentials,
    EmailCode,
    EmailOnly,
    PasswordResetBody,
    challenge_out,
    self_out,
)
from app.services import accounts, otp, verification

router = APIRouter(prefix="/auth", tags=["auth"])

_login_limit = Depends(ratelimit.login_limiter.dependency())
_register_limit = Depends(ratelimit.register_limiter.dependency())
_request_limit = Depends(ratelimit.otp_request_limiter.dependency())
_verify_limit = Depends(ratelimit.otp_verify_limiter.dependency())


@router.get("/me")
async def auth_me(member=Depends(current_member)):
    return {"member": self_out(member)}


@router.post("/register", dependencies=[_register_limit])
async def register(body: Credentials, session: AsyncSession = Depends(get_session)):
    """Start a signup: validates everything and mails a 6-digit code. No account yet."""
    challenge = await verification.start_registration(
        session,
        username=body.username,
        password=body.password,
        email=body.email,
        whatsapp=body.whatsapp,
        invite=body.invite,
    )
    return {"verification": challenge_out(challenge, otp.timers(challenge))}


@router.post("/register/resend", dependencies=[_request_limit])
async def register_resend(body: EmailOnly, session: AsyncSession = Depends(get_session)):
    challenge = await verification.resend_registration(session, body.email)
    return {"verification": challenge_out(challenge, otp.timers(challenge))}


@router.post("/register/verify", dependencies=[_verify_limit])
async def register_verify(body: EmailCode, request: Request, session: AsyncSession = Depends(get_session)):
    member = await verification.complete_registration(session, email=body.email, code=body.code)
    await session.flush()  # ensure id is assigned before we set the cookie
    security.login_session(request, member.id, member.session_version)
    return {"member": self_out(member)}


@router.post("/login", dependencies=[_login_limit])
async def login(body: Credentials, request: Request, session: AsyncSession = Depends(get_session)):
    member = await accounts.authenticate(session, body.username, body.password)
    security.login_session(request, member.id, member.session_version)
    return {"member": self_out(member)}


@router.post("/logout")
async def logout(request: Request):
    security.logout_session(request)
    return {"ok": True}


@router.post("/logout-all")
async def logout_all(
    request: Request, session: AsyncSession = Depends(get_session), member=Depends(require_login)
):
    """Sign out every device, this one included."""
    await accounts.logout_everywhere(session, member)
    security.logout_session(request)
    return {"ok": True}


@router.post("/password/forgot", dependencies=[_request_limit])
async def password_forgot(body: EmailOnly, session: AsyncSession = Depends(get_session)):
    """Always the same answer — whether the email has an account is never revealed."""
    challenge = await verification.request_password_reset(session, body.email)
    return {"verification": challenge_out(challenge, otp.timers(challenge))}


@router.post("/password/resend", dependencies=[_request_limit])
async def password_resend(body: EmailOnly, session: AsyncSession = Depends(get_session)):
    challenge = await verification.resend_password_reset(session, body.email)
    return {"verification": challenge_out(challenge, otp.timers(challenge))}


@router.post("/password/verify", dependencies=[_verify_limit])
async def password_verify(body: EmailCode, session: AsyncSession = Depends(get_session)):
    token, ttl = await verification.verify_password_reset(session, email=body.email, code=body.code)
    return {"resetToken": token, "expiresIn": ttl}


@router.post("/password/reset", dependencies=[_verify_limit])
async def password_reset(body: PasswordResetBody, request: Request, session: AsyncSession = Depends(get_session)):
    member = await verification.complete_password_reset(
        session, token=body.resetToken, new_password=body.newPassword
    )
    security.login_session(request, member.id, member.session_version)
    return {"member": self_out(member)}
