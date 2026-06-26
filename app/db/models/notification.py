"""Notification ORM model — the in-app notification backbone."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Index, String
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
    read: Mapped[bool] = mapped_column(Boolean(create_constraint=False), nullable=False, default=False)
    ts: Mapped[str] = mapped_column(String, nullable=False, default=now_iso)

    __table_args__ = (Index("idx_notif_member", "member_id", "read", "ts"),)
