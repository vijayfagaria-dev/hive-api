"""Fine aggregate ORM models — the complaint and its proofs, audit events, votes.

A fine *is* a complaint. The status enum is small; the "voting" phase is
status='disputed' + a non-null vote_deadline (see services/complaints.py).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain.enums import FineStatus
from app.domain.time import now_iso


class Fine(Base):
    __tablename__ = "fines"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)   # the accused
    rule_id: Mapped[Optional[int]] = mapped_column(ForeignKey("rules.id"))
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    ts: Mapped[str] = mapped_column(String, nullable=False, default=now_iso)
    added_by: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)    # the accuser
    status: Mapped[str] = mapped_column(String, nullable=False, default=FineStatus.PENDING)
    paid: Mapped[bool] = mapped_column(Boolean(create_constraint=False), nullable=False, default=False)
    confirm_deadline: Mapped[Optional[str]] = mapped_column(String)  # pending auto-confirms after this
    dispute_reason: Mapped[Optional[str]] = mapped_column(String)
    vote_deadline: Mapped[Optional[str]] = mapped_column(String)     # set when a vote opens
    resolution: Mapped[Optional[str]] = mapped_column(String)        # accepted|auto_confirmed|upheld|void
    resolved_at: Mapped[Optional[str]] = mapped_column(String)

    # Children of the aggregate. lazy="raise_on_sql": never implicitly lazy-load
    # (unsafe in async) — repositories load these explicitly when needed.
    proofs: Mapped[list["FineProof"]] = relationship(
        cascade="all, delete-orphan", lazy="raise_on_sql"
    )
    events: Mapped[list["FineEvent"]] = relationship(
        cascade="all, delete-orphan", lazy="raise_on_sql"
    )
    votes: Mapped[list["FineVote"]] = relationship(
        cascade="all, delete-orphan", lazy="raise_on_sql"
    )

    __table_args__ = (
        CheckConstraint("amount >= 0", name="amount_non_negative"),
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'disputed', 'void', 'upheld')",
            name="status_valid",
        ),
        Index("idx_fines_member", "member_id"),
        Index("idx_fines_addedby", "added_by"),
        Index("idx_fines_status", "status"),
    )


class FineProof(Base):
    """Mandatory image evidence (>=1 per fine, enforced in the service)."""

    __tablename__ = "fine_proofs"

    id: Mapped[int] = mapped_column(primary_key=True)
    fine_id: Mapped[int] = mapped_column(ForeignKey("fines.id"), nullable=False)
    uploaded_by: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"))
    source: Mapped[str] = mapped_column(String, nullable=False)  # 'upload' | 'telegram'
    ref: Mapped[str] = mapped_column(String, nullable=False)     # disk filename | telegram file_id
    content_type: Mapped[Optional[str]] = mapped_column(String)
    width: Mapped[Optional[int]] = mapped_column(Integer)
    height: Mapped[Optional[int]] = mapped_column(Integer)
    ts: Mapped[str] = mapped_column(String, nullable=False, default=now_iso)

    __table_args__ = (
        CheckConstraint("source IN ('upload', 'telegram')", name="source_valid"),
        Index("idx_proofs_fine", "fine_id"),
    )


class FineEvent(Base):
    """Append-only audit trail row — one per lifecycle step (the timeline)."""

    __tablename__ = "fine_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    fine_id: Mapped[int] = mapped_column(ForeignKey("fines.id"), nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"))  # null = system/sweep
    detail: Mapped[Optional[str]] = mapped_column(String)
    ts: Mapped[str] = mapped_column(String, nullable=False, default=now_iso)

    __table_args__ = (Index("idx_events_fine", "fine_id", "ts"),)


class FineVote(Base):
    """A neutral member's vote on a disputed complaint (one per voter per fine)."""

    __tablename__ = "fine_votes"

    id: Mapped[int] = mapped_column(primary_key=True)
    fine_id: Mapped[int] = mapped_column(ForeignKey("fines.id"), nullable=False)
    voter_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    vote: Mapped[str] = mapped_column(String, nullable=False)
    ts: Mapped[Optional[str]] = mapped_column(String, default=now_iso)

    __table_args__ = (
        UniqueConstraint("fine_id", "voter_id", name="one_vote_per_voter"),
        CheckConstraint("vote IN ('uphold', 'void')", name="vote_valid"),
    )
