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
from app.domain.time import deadline_iso, now, now_iso
from app.repositories import devices as devices_repo
from app.repositories import members as members_repo
from app.repositories import notifications as notifications_repo
from app.repositories import outbox as outbox_repo
from app.repositories import push as push_repo

logger = logging.getLogger("hive.notify")


def rupees(n: int) -> str:
    return f"₹{n:,}"


def _link_url(
    fine_id: Optional[int] = None,
    proposal_id: Optional[int] = None,
    bill_id: Optional[int] = None,
) -> Optional[str]:
    if not settings.app_base_url:
        return None
    if fine_id is not None:
        return f"{settings.app_base_url}/complaints/{fine_id}"
    if proposal_id is not None:
        return f"{settings.app_base_url}/proposals/{proposal_id}"
    if bill_id is not None:
        return f"{settings.app_base_url}/bills"
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
    bill_id: Optional[int] = None,
) -> None:
    """Record the in-app notification (the reliable backbone) and enqueue an outbox row
    for out-of-band delivery — both in the caller's transaction. No network I/O happens
    here; the background dispatcher (main._notify_dispatch_loop) sends push/email/WhatsApp
    in its own session, so a slow send never holds the request's SQLite write lock."""
    await notifications_repo.insert(
        session, member_id=member.id, kind=kind, title=title, body=body,
        fine_id=fine_id, proposal_id=proposal_id, bill_id=bill_id,
    )
    url = _link_url(fine_id=fine_id, proposal_id=proposal_id, bill_id=bill_id)
    tag_id = (
        f"complaint-{fine_id}" if fine_id
        else f"proposal-{proposal_id}" if proposal_id
        else f"bill-{bill_id}" if bill_id
        else None
    )
    await outbox_repo.enqueue(
        session, member_id=member.id, kind=kind, title=title, body=body, url=url, tag=tag_id,
    )


async def notify_members(
    session: AsyncSession,
    members: Sequence[Member],
    *,
    kind: str,
    title: str,
    body: Optional[str] = None,
    fine_id: Optional[int] = None,
    proposal_id: Optional[int] = None,
    bill_id: Optional[int] = None,
) -> None:
    for member in members:
        await notify_member(
            session, member, kind=kind, title=title, body=body,
            fine_id=fine_id, proposal_id=proposal_id, bill_id=bill_id,
        )


# --- Channel senders (network; called by the dispatcher, never in a request txn) ---

def _send_webpush_sync(endpoint: str, p256dh: str, auth: str, payload: str) -> None:
    from pywebpush import webpush  # lazy: module loads even without the lib

    webpush(
        subscription_info={"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}},
        data=payload,
        vapid_private_key=settings.vapid_private_key,
        vapid_claims={"sub": settings.vapid_subject},
    )


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


# --- Channel registry (pluggable providers — add one by appending to CHANNELS) ---

class _FcmTokenGone(Exception):
    """FCM reported the token is unregistered/invalid — prune it."""


_FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_fcm_credentials = None  # cached google.auth service-account credentials


def _fcm_bearer() -> str:
    """A valid FCM OAuth bearer token. Prefers a service-account file (self-refreshing via
    google-auth); falls back to a pre-minted FCM_ACCESS_TOKEN for quick testing. Sync
    (does network on refresh) — call from a threadpool."""
    if settings.fcm_credentials_file:
        from google.auth.transport.requests import Request  # lazy: only when FCM is on
        from google.oauth2 import service_account

        global _fcm_credentials
        if _fcm_credentials is None:
            _fcm_credentials = service_account.Credentials.from_service_account_file(
                settings.fcm_credentials_file, scopes=[_FCM_SCOPE]
            )
        if not _fcm_credentials.valid:
            _fcm_credentials.refresh(Request())
        return _fcm_credentials.token
    return settings.fcm_access_token


async def _send_fcm(token: str, job: dict) -> None:
    """Deliver one message via FCM HTTP v1 — covers native Android + iOS-via-APNS. Inert
    unless FCM is configured (config.fcm_*); FCM message delivery itself has no cost."""
    import httpx

    bearer = await run_in_threadpool(_fcm_bearer)
    endpoint = f"https://fcm.googleapis.com/v1/projects/{settings.fcm_project_id}/messages:send"
    message = {
        "message": {
            "token": token,
            "notification": {"title": job["title"], "body": job["body"] or ""},
            "data": {"url": job["url"] or "", "tag": job["tag"] or "hive"},
        }
    }
    headers = {"Authorization": f"Bearer {bearer}"}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(endpoint, json=message, headers=headers)
        if resp.status_code in (403, 404):  # UNREGISTERED / invalid token
            raise _FcmTokenGone(token)
        resp.raise_for_status()


class Channel:
    """A delivery provider. `enabled()` gates it on config; `send(job)` delivers and
    returns dead push targets to prune, as (provider, token) pairs."""

    name = "base"

    def enabled(self) -> bool:
        return False

    async def send(self, job: dict) -> list[tuple[str, str]]:
        return []


class WebPushChannel(Channel):
    name = "webpush"

    def enabled(self) -> bool:
        return settings.push_enabled

    async def send(self, job: dict) -> list[tuple[str, str]]:
        dead: list[tuple[str, str]] = []
        if not job["webpush"]:
            return dead
        payload = json.dumps(
            {"title": job["title"], "body": job["body"] or "", "url": job["url"], "tag": job["tag"] or "hive"}
        )
        for endpoint, p256dh, auth in job["webpush"]:
            try:
                await run_in_threadpool(_send_webpush_sync, endpoint, p256dh, auth, payload)
            except Exception as exc:  # WebPushException among others
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status in (404, 410):
                    dead.append(("webpush", endpoint))
                else:
                    logger.warning("Web Push to member %s failed (non-fatal)", job["member_id"], exc_info=True)
        return dead


class FcmChannel(Channel):
    name = "fcm"

    def enabled(self) -> bool:
        return settings.fcm_enabled

    async def send(self, job: dict) -> list[tuple[str, str]]:
        dead: list[tuple[str, str]] = []
        for token in job["fcm"]:
            try:
                await _send_fcm(token, job)
            except _FcmTokenGone:
                dead.append(("fcm", token))
            except Exception:
                logger.warning("FCM to member %s failed (non-fatal)", job["member_id"], exc_info=True)
        return dead


class EmailChannel(Channel):
    name = "email"

    def enabled(self) -> bool:
        return settings.email_enabled

    async def send(self, job: dict) -> list[tuple[str, str]]:
        if not job["email"]:
            return []
        text = job["body"] or ""
        if job["url"]:
            text = f"{text}\n\nOpen it: {job['url']}"
        try:
            await run_in_threadpool(_send_email_sync, job["email"], job["title"], text)
        except Exception:
            logger.warning("Email to %s failed (non-fatal)", job["email"], exc_info=True)
        return []


class WhatsAppChannel(Channel):
    name = "whatsapp"

    def enabled(self) -> bool:
        return settings.whatsapp_enabled

    async def send(self, job: dict) -> list[tuple[str, str]]:
        if not job["whatsapp"]:
            return []
        try:
            await _send_whatsapp_request(job["whatsapp"], _wa_param(job["title"], job["body"], job["url"]))
        except Exception:
            logger.warning("WhatsApp to member %s failed (non-fatal)", job["member_id"], exc_info=True)
        return []


# The pluggable provider set — add a channel by appending here; nothing else changes.
CHANNELS: list[Channel] = [WebPushChannel(), FcmChannel(), EmailChannel(), WhatsAppChannel()]


# --- Outbox dispatcher (drains the queue in the background sweep) -----------

async def _deliver_job(job: dict) -> list[tuple[str, str]]:
    """Best-effort delivery across every enabled channel. Runs with NO database session
    open — network I/O stays out of the write lock. Returns dead push targets to prune,
    as (provider, token) pairs."""
    dead: list[tuple[str, str]] = []
    for channel in CHANNELS:
        if channel.enabled():
            try:
                dead.extend(await channel.send(job))
            except Exception:
                logger.warning("Notification channel %s failed (non-fatal)", channel.name, exc_info=True)
    return dead


async def dispatch_outbox(limit: int = 25) -> int:
    """Drain a batch of the notification outbox. Three short phases keep network I/O
    strictly outside the DB transaction: (A) claim + preload recipient targets in one
    session, (B) send with no session open, (C) finalize statuses + prune dead devices in
    one session. Returns how many jobs were processed. Called by the sweep loop."""
    from app.db import session as db  # local import avoids any import-time coupling

    # Phase A — claim due rows and preload every channel's targets.
    async with db.session_scope() as s:
        rows = await outbox_repo.claim_batch(s, now_iso(), limit)
        jobs: list[dict] = []
        for r in rows:
            member = await members_repo.get(s, r.member_id)
            webpush: list[tuple] = []
            if settings.push_enabled:
                webpush += [(x.endpoint, x.p256dh, x.auth) for x in await push_repo.list_for(s, r.member_id)]
                webpush += [(d.token, d.p256dh, d.auth) for d in await devices_repo.list_for(s, r.member_id, "webpush")]
            fcm = [d.token for d in await devices_repo.list_for(s, r.member_id, "fcm")] if settings.fcm_enabled else []
            jobs.append({
                "id": r.id, "kind": r.kind, "title": r.title, "body": r.body,
                "url": r.url, "tag": r.tag, "member_id": r.member_id,
                "email": getattr(member, "email", None),
                "whatsapp": getattr(member, "whatsapp", None),
                "webpush": webpush, "fcm": fcm,
            })
    if not jobs:
        return 0

    # Phase B — send (no DB session held).
    outcomes: list[tuple[int, str, list[tuple[str, str]], str | None]] = []
    for job in jobs:
        try:
            dead = await _deliver_job(job)
            outcomes.append((job["id"], "sent", dead, None))
        except Exception as exc:  # a whole-job failure -> retry with backoff
            outcomes.append((job["id"], "retry", [], repr(exc)))

    # Phase C — persist results + prune dead push targets (both new and legacy tables).
    async with db.session_scope() as s:
        for outbox_id, result, dead, err in outcomes:
            if result == "sent":
                await outbox_repo.mark_sent(s, outbox_id, now_iso())
            else:
                await outbox_repo.mark_retry(
                    s, outbox_id, next_attempt_at=deadline_iso(now(), 1), error=err or "",
                )
            for provider, token in dead:
                await devices_repo.delete_by_token(s, token)
                if provider == "webpush":
                    await push_repo.delete_by_endpoint(s, token)  # legacy table too
    return len(jobs)


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


# --- Bills (declare-and-confirm) -------------------------------------------

async def bill_claimed(
    session: AsyncSession,
    *,
    recipients: Sequence[Member],
    bill_id: int,
    payer_name: str,
    bill_type: str,
    amount: int,
    confirm_hours: int,
) -> None:
    await notify_members(
        session, recipients, kind="bill_claimed", bill_id=bill_id,
        title=f"🧾 {payer_name} paid the {bill_type} bill — {rupees(amount)}",
        body=(f"They've claimed it's paid. Dispute it in the app within {confirm_hours}h "
              f"if that's wrong — otherwise it auto-confirms."),
    )


async def bill_disputed(
    session: AsyncSession,
    *,
    recipients: Sequence[Member],
    bill_id: int,
    disputer_name: str,
    bill_type: str,
    reason: Optional[str] = None,
) -> None:
    tail = f" — “{reason}”" if reason else ""
    await notify_members(
        session, recipients, kind="bill_disputed", bill_id=bill_id,
        title=f"⚠️ {disputer_name} disputed the {bill_type} bill",
        body=f"It won't auto-confirm until the flat sorts it out{tail}.",
    )


async def bill_auto_confirmed(
    session: AsyncSession,
    *,
    recipients: Sequence[Member],
    bill_id: int,
    bill_type: str,
    amount: int,
) -> None:
    await notify_members(
        session, recipients, kind="bill_auto_confirmed", bill_id=bill_id,
        title=f"✅ {bill_type.capitalize()} bill confirmed — {rupees(amount)}",
        body="Nobody disputed it in time, so it's settled.",
    )


# --- Expenses ---------------------------------------------------------------

async def expense_added(
    session: AsyncSession, *, recipients: Sequence[Member], expense_id: int,
    payer_name: str, category: str, amount: int,
) -> None:
    await notify_members(
        session, recipients, kind="expense_added",
        title=f"🧾 {payer_name} added a {category} expense — {rupees(amount)}",
        body="Open Expenses to see your share and settle up.",
    )


async def recurring_failed(
    session: AsyncSession, *, recipients: Sequence[Member], template_name: str, month: str,
    reason: Optional[str] = None,
) -> None:
    tail = f" ({reason[:120]})" if reason else ""
    await notify_members(
        session, recipients, kind="recurring_failed",
        title=f"⚠️ Auto-expense paused — {template_name}",
        body=(f"Couldn't auto-generate “{template_name}” for {month}{tail}. It's paused — "
              f"fix the template (e.g. splits must total 100%) and re-activate it."),
    )


async def settle_proposed(session: AsyncSession, *, debtor: Member, to_name: str, amount: int) -> None:
    await notify_member(
        session, debtor, kind="settle_proposed",
        title=f"💸 Settle up — pay {to_name} {rupees(amount)}",
        body="Open Settle Up to clear it in a tap.",
    )


async def rent_completed(session: AsyncSession, *, recipients: Sequence[Member], month: str, target: int) -> None:
    await notify_members(
        session, recipients, kind="rent_completed",
        title=f"✅ Rent complete — {month}",
        body=f"The full {rupees(target)} is in for {month}. 🎉",
    )


async def rent_incomplete(session: AsyncSession, *, recipients: Sequence[Member], month: str, remaining: int) -> None:
    await notify_members(
        session, recipients, kind="rent_incomplete",
        title=f"⏳ Rent still short — {month}",
        body=f"{rupees(remaining)} left to reach this month's target.",
    )


# --- Money settlement -------------------------------------------------------

async def settlement_closed(
    session: AsyncSession, *, recipients: Sequence[Member], period: str, pot: int, leftover: int
) -> None:
    await notify_members(
        session, recipients, kind="settlement_closed",
        title=f"📊 Settlement closed — {period}",
        body=(f"Fine pot {rupees(pot)} went toward rent; {rupees(leftover)} left over, "
              f"split back by share. Open My Money for your statement."),
    )
