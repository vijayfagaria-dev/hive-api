"""Transactional mail (OTP codes, security notices) — sent only after commit.

Auth mail can't ride the notification outbox (a signup has no member row yet) and
must not be sent inside the request transaction (a slow SMTP handshake would hold
SQLite's write lock, and a rolled-back request must never mail out a code that was
never stored). So services call `send_after_commit(session, message)`: messages
queue on the session and a commit hook hands them to a background task; a rollback
drops them.

With SMTP unconfigured (local dev) the message is logged instead — including the
code, so the flow can be exercised without a mail server.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Callable

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import settings

logger = logging.getLogger("hive.mail")

_QUEUE_KEY = "outgoing_mail"


@dataclass(frozen=True)
class Message:
    to: str
    subject: str
    text: str
    html: str


def _smtp_send(message: Message) -> None:
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = message.to
    msg["Subject"] = message.subject
    msg.set_content(message.text)
    msg.add_alternative(message.html, subtype="html")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(msg)


def _dev_log(message: Message) -> None:
    logger.warning(
        "SMTP not configured — email NOT sent (dev only). To: %s | %s\n%s",
        message.to, message.subject, message.text,
    )


def _default_transport(message: Message) -> None:
    if settings.email_enabled:
        _smtp_send(message)
    else:
        _dev_log(message)


# Swappable delivery function (tests capture mail by replacing it).
transport: Callable[[Message], None] = _default_transport

_inflight: set[asyncio.Task] = set()


async def _deliver(message: Message) -> None:
    try:
        await run_in_threadpool(transport, message)
    except Exception:
        logger.warning("Email to %s failed", message.to, exc_info=True)


def send_after_commit(session: AsyncSession, message: Message) -> None:
    """Queue `message` to go out once the session's transaction commits."""
    session.sync_session.info.setdefault(_QUEUE_KEY, []).append(message)


@event.listens_for(Session, "after_commit")
def _flush_queue(sync_session: Session) -> None:
    queued = sync_session.info.pop(_QUEUE_KEY, None)
    if not queued:
        return
    loop = asyncio.get_running_loop()
    for message in queued:
        task = loop.create_task(_deliver(message))
        _inflight.add(task)
        task.add_done_callback(_inflight.discard)


@event.listens_for(Session, "after_rollback")
def _drop_queue(sync_session: Session) -> None:
    sync_session.info.pop(_QUEUE_KEY, None)


async def drain() -> None:
    """Wait for in-flight sends (shutdown, tests)."""
    if _inflight:
        await asyncio.gather(*list(_inflight), return_exceptions=True)
