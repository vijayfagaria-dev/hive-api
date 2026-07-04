"""Account routes — the member's own notification channels (email, WhatsApp, push) + password."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_login
from app.core.config import settings
from app.core.errors import DomainError
from app.repositories import devices as devices_repo
from app.repositories import push as push_repo
from app.schemas.accounts import EmailBody, PasswordChangeBody, WhatsappBody
from app.schemas.push import PushSubscribeBody, PushUnsubscribeBody
from app.services import accounts

_PUSH_PROVIDERS = {"webpush", "fcm", "apns"}
_PUSH_PLATFORMS = {"web", "android", "ios"}

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
    """Register a push device (provider-agnostic). Web Push = `{endpoint, keys}` (as before)
    or `{provider:'webpush', token, keys}`; native = `{provider:'fcm', platform, token}`."""
    provider = (body.provider or "webpush").strip()
    platform = (body.platform or "web").strip()
    if provider not in _PUSH_PROVIDERS:
        raise DomainError(f"Unknown push provider {provider!r}.")
    if platform not in _PUSH_PLATFORMS:
        raise DomainError(f"Unknown platform {platform!r}.")
    token = body.token or body.endpoint
    if not token:
        raise DomainError("A device token (or web-push endpoint) is required.")
    p256dh = auth = None
    if provider == "webpush":
        if body.keys is None:
            raise DomainError("Web Push needs p256dh + auth keys.")
        p256dh, auth = body.keys.p256dh, body.keys.auth
    await devices_repo.upsert(
        session, member_id=member.id, provider=provider, platform=platform,
        token=token, p256dh=p256dh, auth=auth,
    )
    return {"ok": True}


@router.post("/push/unsubscribe")
async def push_unsubscribe(
    body: PushUnsubscribeBody, session: AsyncSession = Depends(get_session), member=Depends(require_login)
):
    # Remove from the new device table and the legacy web-push table (endpoint == token).
    await devices_repo.delete_by_token(session, body.endpoint)
    await push_repo.delete_by_endpoint(session, body.endpoint)
    return {"ok": True}
