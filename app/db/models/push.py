"""Web Push subscription ORM model (VAPID) — one row per granted device."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.time import now_iso


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    endpoint: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    p256dh: Mapped[str] = mapped_column(String, nullable=False)
    auth: Mapped[str] = mapped_column(String, nullable=False)
    ts: Mapped[str] = mapped_column(String, nullable=False, default=now_iso)

    __table_args__ = (Index("idx_push_member", "member_id"),)
