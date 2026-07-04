"""Notification-outbox data access — enqueue in the request txn, drain in the sweep."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import NotificationOutbox
from app.domain.time import now_iso


async def enqueue(
    session: AsyncSession,
    *,
    member_id: int,
    kind: str,
    title: str,
    body: Optional[str] = None,
    url: Optional[str] = None,
    tag: Optional[str] = None,
    next_attempt_at: Optional[str] = None,
) -> NotificationOutbox:
    row = NotificationOutbox(
        member_id=member_id, kind=kind, title=title, body=body, url=url, tag=tag,
        next_attempt_at=next_attempt_at or now_iso(),
    )
    session.add(row)
    await session.flush()
    return row


async def claim_batch(
    session: AsyncSession, now_iso_str: str, limit: int
) -> list[NotificationOutbox]:
    """The next due, still-pending rows (oldest first). The dispatcher loop is a single
    sequential task, so no row-level lease/'sending' state is needed to avoid double
    sends; a crash mid-send simply leaves rows pending for at-least-once redelivery."""
    return list(
        await session.scalars(
            select(NotificationOutbox)
            .where(
                NotificationOutbox.status == "pending",
                NotificationOutbox.next_attempt_at <= now_iso_str,
            )
            .order_by(NotificationOutbox.id)
            .limit(limit)
        )
    )


async def mark_sent(session: AsyncSession, outbox_id: int, at: str) -> None:
    row = await session.get(NotificationOutbox, outbox_id)
    if row is not None:
        row.status = "sent"
        row.sent_at = at
        row.attempts += 1


async def mark_retry(
    session: AsyncSession, outbox_id: int, *, next_attempt_at: str, error: str, max_attempts: int = 5
) -> None:
    """Bump the attempt count; reschedule, or dead-letter ('failed') past the cap."""
    row = await session.get(NotificationOutbox, outbox_id)
    if row is None:
        return
    row.attempts += 1
    row.last_error = (error or "")[:500]
    if row.attempts >= max_attempts:
        row.status = "failed"
    else:
        row.next_attempt_at = next_attempt_at
