"""Notification ORM models — the in-app backbone + the out-of-band delivery outbox."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.time import now_iso


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[Optional[str]] = mapped_column(String)
    fine_id: Mapped[Optional[int]] = mapped_column(ForeignKey("fines.id"))            # deep-link target
    proposal_id: Mapped[Optional[int]] = mapped_column(ForeignKey("rule_proposals.id"))  # deep-link target
    bill_id: Mapped[Optional[int]] = mapped_column(ForeignKey("bills.id"))            # deep-link target
    read: Mapped[bool] = mapped_column(Boolean(create_constraint=False), nullable=False, default=False)
    ts: Mapped[str] = mapped_column(String, nullable=False, default=now_iso)

    __table_args__ = (Index("idx_notif_member", "member_id", "read", "ts"),)


class NotificationOutbox(Base):
    """Durable queue for out-of-band delivery (Web Push / email / WhatsApp).

    The in-app `Notification` row is written synchronously in the request transaction
    (the reliable backbone); this row is enqueued in that *same* transaction, and a
    background dispatcher (main._notify_dispatch_loop) sends the external channels in its
    own session — so slow network I/O never runs inside a request's SQLite write lock
    (the old availability hazard). `url`/`tag` are precomputed at enqueue so the
    dispatcher needs no entity resolution.
    """

    __tablename__ = "notification_outbox"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[Optional[str]] = mapped_column(String)
    url: Mapped[Optional[str]] = mapped_column(String)   # precomputed deep-link
    tag: Mapped[Optional[str]] = mapped_column(String)   # collapse key for push
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")  # pending|sent|failed
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[str] = mapped_column(String, nullable=False, default=now_iso)
    last_error: Mapped[Optional[str]] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_iso)
    sent_at: Mapped[Optional[str]] = mapped_column(String)

    __table_args__ = (
        CheckConstraint("status IN ('pending', 'sent', 'failed')", name="outbox_status_valid"),
        Index("idx_outbox_pending", "status", "next_attempt_at"),
    )
