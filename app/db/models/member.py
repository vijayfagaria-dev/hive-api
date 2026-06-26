"""Member ORM model — tenants and guests."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.enums import Role
from app.domain.time import now_iso


class Member(Base):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # Legacy (Telegram bot retired): kept so existing rows map cleanly.
    telegram_id: Mapped[Optional[int]] = mapped_column(Integer, unique=True)
    username: Mapped[Optional[str]] = mapped_column(String)        # web login; unique via lower() index
    password_hash: Mapped[Optional[str]] = mapped_column(String)  # bcrypt; NULL until set
    email: Mapped[Optional[str]] = mapped_column(String)          # email notification channel
    whatsapp: Mapped[Optional[str]] = mapped_column(String)       # E.164; WhatsApp channel
    role: Mapped[str] = mapped_column(String, nullable=False, default=Role.TENANT)
    is_active: Mapped[bool] = mapped_column(Boolean(create_constraint=False), nullable=False, default=True)
    joined_on: Mapped[str] = mapped_column(String, nullable=False, default=now_iso)
    left_on: Mapped[Optional[str]] = mapped_column(String)
    host_id: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"))  # legacy: a guest's inviting tenant

    __table_args__ = (
        CheckConstraint("role IN ('tenant', 'guest')", name="role_valid"),
        CheckConstraint("role = 'guest' OR host_id IS NULL", name="host_only_for_guest"),
    )


# Case-insensitive unique username (functional index; matches the legacy schema).
Index("idx_members_username", func.lower(Member.username), unique=True)
