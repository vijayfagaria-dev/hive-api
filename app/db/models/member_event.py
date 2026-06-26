"""Member audit trail — append-only record of household-management actions.

Mirrors the FineEvent / ProposalEvent pattern: one row per action on a member
(role change, removal, rename, invite-accept…). `actor_id` is who performed it
(null = system / self-registration); `old_value`/`new_value` capture the change.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.time import now_iso


class MemberEvent(Base):
    __tablename__ = "member_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)  # the target
    type: Mapped[str] = mapped_column(String, nullable=False)
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"))  # null = system
    detail: Mapped[Optional[str]] = mapped_column(String)
    old_value: Mapped[Optional[str]] = mapped_column(String)
    new_value: Mapped[Optional[str]] = mapped_column(String)
    ts: Mapped[str] = mapped_column(String, nullable=False, default=now_iso)

    __table_args__ = (Index("idx_mevents_member", "member_id", "ts"),)
