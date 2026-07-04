"""Push device models.

`PushSubscription` is the legacy Web-Push-only table (kept for existing subscriptions).
`Device` is the provider-agnostic replacement (Bug 3): one row per registered device,
across Web Push, FCM (Android + iOS-via-APNS), or APNS — so a native app token has a
home. New registrations write `Device`; the Web Push channel reads both.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, String
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


class Device(Base):
    """A provider-agnostic push target. `token` is the Web Push endpoint OR the FCM/APNS
    registration token; `p256dh`/`auth` are Web-Push-only. Upserted by token (a rotated
    token just re-points), so we never reject a legitimate re-registration."""

    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    platform: Mapped[str] = mapped_column(String, nullable=False, default="web")     # web|android|ios
    provider: Mapped[str] = mapped_column(String, nullable=False, default="webpush")  # webpush|fcm|apns
    token: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    p256dh: Mapped[Optional[str]] = mapped_column(String)  # webpush only
    auth: Mapped[Optional[str]] = mapped_column(String)    # webpush only
    active: Mapped[bool] = mapped_column(Boolean(create_constraint=False), nullable=False, default=True)
    last_seen: Mapped[str] = mapped_column(String, nullable=False, default=now_iso)

    __table_args__ = (
        CheckConstraint("provider IN ('webpush', 'fcm', 'apns')", name="device_provider_valid"),
        CheckConstraint("platform IN ('web', 'android', 'ios')", name="device_platform_valid"),
        Index("idx_devices_member_provider", "member_id", "provider"),
    )
