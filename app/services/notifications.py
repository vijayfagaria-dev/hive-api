"""Notifications — the one place that fans an event out across channels.

Channels, in priority order, all best-effort except the first:
  1. In-app (always): a `notifications` row — the reliable backbone the web polls.
  2. Web Push (VAPID): Android + installed iOS PWAs; dead subs pruned on 404/410.
  3. Email (SMTP): the iPhone-without-PWA fallback.
  4. WhatsApp (Meta Cloud API): template message when configured.

Channels 2–4 never break the surrounding transaction — each send is wrapped and
run off the event loop where it blocks. Callers use the high-level `complaint_*`
helpers; a new channel slots in beside the others without touching them.
"""

from __future__ import annotations

import json
import logging
import smtplib
from email.message import EmailMessage
from typing import Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.db.models import Member
from app.repositories import notifications as notifications_repo
from app.repositories import push as push_repo

logger = logging.getLogger("hive.notify")


def rupees(n: int) -> str:
    return f"₹{n:,}"


def _link_url(fine_id: Optional[int] = None, proposal_id: Optional[int] = None) -> Optional[str]:
    if not settings.app_base_url:
        return None
    if fine_id is not None:
        return f"{settings.app_base_url}/complaints/{fine_id}"
    if proposal_id is not None:
        return f"{settings.app_base_url}/proposals/{proposal_id}"
    return None


# --- Core fan-out ----------------------------------------------------------

async def notify_member(
    session: AsyncSession,
    member: Member,
    *,
    kind: str,
    title: str,
    body: Optional[str] = None,
    fine_id: Optional[int] = None,
    proposal_id: Optional[int] = None,
) -> None:
    """Record an in-app notification, then push + email + WhatsApp best-effort."""
    await notifications_repo.insert(
        session, member_id=member.id, kind=kind, title=title, body=body,
        fine_id=fine_id, proposal_id=proposal_id,
    )
    url = _link_url(fine_id=fine_id, proposal_id=proposal_id)
    tag_id = f"complaint-{fine_id}" if fine_id else (f"proposal-{proposal_id}" if proposal_id else None)
    await _push_web(session, member, title=title, body=body, url=url, tag_id=tag_id)
    await _send_email(member, subject=title, body=body, url=url)
    await _send_whatsapp(member, title=title, body=body, url=url)


async def notify_members(
    session: AsyncSession,
    members: Sequence[Member],
    *,
    kind: str,
    title: str,
    body: Optional[str] = None,
    fine_id: Optional[int] = None,
    proposal_id: Optional[int] = None,
) -> None:
    for member in members:
        await notify_member(
            session, member, kind=kind, title=title, body=body,
            fine_id=fine_id, proposal_id=proposal_id,
        )


# --- Web Push channel ------------------------------------------------------

async def _push_web(session, member: Member, *, title, body, url, tag_id=None) -> None:
    if not settings.push_enabled:
        return
    subs = await push_repo.list_for(session, member.id)
    if not subs:
        return
    payload = json.dumps(
        {"title": title, "body": body or "", "url": url, "tag": tag_id or "hive"}
    )
    for sub in subs:
        try:
            await run_in_threadpool(_send_webpush_sync, sub.endpoint, sub.p256dh, sub.auth, payload)
        except Exception as exc:  # WebPushException among others
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                await push_repo.delete_by_endpoint(session, sub.endpoint)
                logger.info("Pruned dead push subscription for member %s", member.id)
            else:
                logger.warning("Web Push to member %s failed (non-fatal)", member.id, exc_info=True)


def _send_webpush_sync(endpoint: str, p256dh: str, auth: str, payload: str) -> None:
    from pywebpush import webpush  # lazy: module loads even without the lib

    webpush(
        subscription_info={"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}},
        data=payload,
        vapid_private_key=settings.vapid_private_key,
        vapid_claims={"sub": settings.vapid_subject},
    )


# --- Email channel ---------------------------------------------------------

async def _send_email(member: Member, *, subject, body, url) -> None:
    if not settings.email_enabled or not member.email:
        return
    text = body or ""
    if url:
        text = f"{text}\n\nOpen it: {url}"
    try:
        await run_in_threadpool(_send_email_sync, member.email, subject, text)
    except Exception:
        logger.warning("Email to %s failed (non-fatal)", member.email, exc_info=True)


def _send_email_sync(to_addr: str, subject: str, text: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(text or subject)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(msg)


# --- WhatsApp channel (official Cloud API; template messages) --------------

def _wa_param(title: str, body: Optional[str], url: Optional[str]) -> str:
    """One template body parameter ({{1}}). WhatsApp forbids newlines/tabs/4+
    spaces in template params, so flatten all whitespace to single spaces."""
    raw = title
    if body:
        raw += f" — {body}"
    if url:
        raw += f" {url}"
    return " ".join(raw.split())[:1000]


async def _send_whatsapp(member: Member, *, title, body, url) -> None:
    if not settings.whatsapp_enabled or not member.whatsapp:
        return
    try:
        await _send_whatsapp_request(member.whatsapp, _wa_param(title, body, url))
    except Exception:
        logger.warning("WhatsApp to member %s failed (non-fatal)", member.id, exc_info=True)


async def _send_whatsapp_request(to: str, text: str) -> None:
    import httpx  # async; already a dependency

    endpoint = (
        f"https://graph.facebook.com/{settings.whatsapp_api_version}"
        f"/{settings.whatsapp_phone_id}/messages"
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": settings.whatsapp_template,
            "language": {"code": settings.whatsapp_lang},
            "components": [{"type": "body", "parameters": [{"type": "text", "text": text}]}],
        },
    }
    headers = {"Authorization": f"Bearer {settings.whatsapp_token}"}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(endpoint, json=payload, headers=headers)
        resp.raise_for_status()


# --- High-level complaint events (called by the complaints service) --------

async def complaint_raised(
    session: AsyncSession,
    *,
    accused: Member,
    accuser_name: str,
    reason: str,
    amount: int,
    fine_id: int,
    cooling_hours: int,
) -> None:
    await notify_member(
        session, accused, kind="complaint_raised",
        title=f"🚨 New complaint about you — {rupees(amount)}",
        body=(f"“{reason}” (reported by {accuser_name}). Open the app to Accept it, "
              f"or Deny it to put it to a flat vote. It auto-confirms in {cooling_hours}h "
              f"if you do nothing."),
        fine_id=fine_id,
    )


async def vote_requested(
    session: AsyncSession,
    *,
    voters: Sequence[Member],
    accused_name: str,
    accuser_name: str,
    reason: str,
    amount: int,
    fine_id: int,
) -> None:
    await notify_members(
        session, voters, kind="vote_requested",
        title="🗳️ Your vote is needed",
        body=(f"{accuser_name} says {accused_name} broke a rule ({rupees(amount)}): "
              f"“{reason}”. {accused_name} denies it. Open the app to Uphold or Void it."),
        fine_id=fine_id,
    )


async def complaint_resolved(
    session: AsyncSession,
    *,
    recipients: Sequence[Member],
    fine_id: int,
    title: str,
    body: Optional[str] = None,
    kind: str = "complaint_resolved",
) -> None:
    await notify_members(session, recipients, kind=kind, title=title, body=body, fine_id=fine_id)


# --- Rule-proposal events --------------------------------------------------

async def proposal_voting_opened(
    session: AsyncSession, *, voters: Sequence[Member], proposal_id: int, title: str
) -> None:
    await notify_members(
        session, voters, kind="proposal_voting", proposal_id=proposal_id,
        title="🗳️ New rule proposal — your vote's needed",
        body=f"“{title}” is open for a vote. Open the app to vote Yes / No.",
    )


async def proposal_commented(
    session: AsyncSession, *, recipients: Sequence[Member], proposal_id: int, by: str, title: str
) -> None:
    await notify_members(
        session, recipients, kind="proposal_comment", proposal_id=proposal_id,
        title="💬 New comment on a proposal",
        body=f"{by} commented on “{title}”.",
    )


async def proposal_resolved(
    session: AsyncSession,
    *,
    recipients: Sequence[Member],
    proposal_id: int,
    title: str,
    body: Optional[str] = None,
    kind: str = "proposal_resolved",
) -> None:
    await notify_members(
        session, recipients, kind=kind, proposal_id=proposal_id, title=title, body=body
    )


# --- Household user management ----------------------------------------------

async def member_role_changed(session: AsyncSession, *, member: Member, by: str, role: str) -> None:
    await notify_member(
        session, member, kind="member_role_changed",
        title="🛡️ Your role changed", body=f"{by} set your role to {role}.",
    )


async def member_removed(session: AsyncSession, *, member: Member, by: str) -> None:
    await notify_member(
        session, member, kind="member_removed",
        title="👋 Removed from the household", body=f"{by} removed you from the flat.",
    )


async def invite_accepted(session: AsyncSession, *, inviter: Member, who: str) -> None:
    await notify_member(
        session, inviter, kind="member_invite_accepted",
        title="✅ Invite accepted", body=f"{who} joined the household.",
    )
