"""Auth routes — register / login / logout / me."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.api.deps import current_member, get_session
from app.core import security
from app.schemas.accounts import Credentials, self_out
from app.services import accounts

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me")
async def auth_me(member=Depends(current_member)):
    return {"member": self_out(member)}


@router.post("/register")
async def register(body: Credentials, request: Request, session: AsyncSession = Depends(get_session)):
    member = await accounts.register(
        session,
        username=body.username,
        password=body.password,
        email=body.email,
        whatsapp=body.whatsapp,
    )
    await session.flush()  # ensure id is assigned before we set the cookie
    security.login_session(request, member.id)
    return {"member": self_out(member)}


@router.post("/login")
async def login(body: Credentials, request: Request, session: AsyncSession = Depends(get_session)):
    member = await accounts.authenticate(session, body.username, body.password)
    security.login_session(request, member.id)
    return {"member": self_out(member)}


@router.post("/logout")
async def logout(request: Request):
    security.logout_session(request)
    return {"ok": True}
