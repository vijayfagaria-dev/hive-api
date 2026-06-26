"""Notification routes (the in-app feed)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_login
from app.repositories import notifications as notifications_repo
from app.schemas.notifications import notification_out

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    unread: bool = False,
    session: AsyncSession = Depends(get_session),
    member=Depends(require_login),
):
    rows = await notifications_repo.list_for(session, member.id, unread_only=unread)
    return {
        "notifications": [notification_out(n) for n in rows],
        "unread": await notifications_repo.unread_count(session, member.id),
    }


@router.post("/{notif_id}/read")
async def mark_read(
    notif_id: int, session: AsyncSession = Depends(get_session), member=Depends(require_login)
):
    changed = await notifications_repo.mark_read(session, member.id, notif_id)
    return {"ok": True, "changed": changed}


@router.post("/read-all")
async def mark_all_read(session: AsyncSession = Depends(get_session), member=Depends(require_login)):
    n = await notifications_repo.mark_all_read(session, member.id)
    return {"ok": True, "marked": n}
