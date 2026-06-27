"""Account routes — the member's own notification channels (email, WhatsApp, push) + password."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_login
from app.core.config import settings
from app.repositories import push as push_repo
from app.schemas.accounts import EmailBody, PasswordChangeBody, WhatsappBody
from app.schemas.push import PushSubscribeBody, PushUnsubscribeBody
from app.services import accounts

router = APIRouter(tags=["account"])


@router.post("/account/email")
async def set_email(
    body: EmailBody, session: AsyncSession = Depends(get_session), member=Depends(require_login)
):
    email = await accounts.set_email(session, member, body.email)
    return {"ok": True, "email": email}


@router.post("/account/whatsapp")
async def set_whatsapp(
    body: WhatsappBody, session: AsyncSession = Depends(get_session), member=Depends(require_login)
):
    number = await accounts.set_whatsapp(session, member, body.whatsapp)
    return {"ok": True, "whatsapp": number}


@router.post("/account/password")
async def change_password(
    body: PasswordChangeBody, session: AsyncSession = Depends(get_session), member=Depends(require_login)
):
    await accounts.change_password(session, member, body.currentPassword, body.newPassword)
    return {"ok": True}


@router.get("/push/public-key")
async def push_public_key():
    """VAPID public key for the frontend to subscribe, or null if Web Push is off."""
    return {"key": settings.vapid_public_key or None}


@router.post("/push/subscribe")
async def push_subscribe(
    body: PushSubscribeBody, session: AsyncSession = Depends(get_session), member=Depends(require_login)
):
    await push_repo.upsert(
        session, member_id=member.id, endpoint=body.endpoint,
        p256dh=body.keys.p256dh, auth=body.keys.auth,
    )
    return {"ok": True}


@router.post("/push/unsubscribe")
async def push_unsubscribe(
    body: PushUnsubscribeBody, session: AsyncSession = Depends(get_session), member=Depends(require_login)
):
    await push_repo.delete_by_endpoint(session, body.endpoint)
    return {"ok": True}
