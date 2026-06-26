"""Rule-proposal aggregate — the community vote to change the rule book.

A proposal is voted on by tenants; if it passes the configurable conditions it's
merged into `rules` (with an immutable `rule_versions` snapshot). The proposal row
carries an optimistic-lock `version` so concurrent lifecycle transitions (a vote
race vs the background close) can't silently clobber each other.
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
from app.domain.enums import ProposalStatus
from app.domain.time import now_iso


class RuleProposal(Base):
    __tablename__ = "rule_proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    proposer_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)        # new_rule|modify_rule|delete_rule
    status: Mapped[str] = mapped_column(String, nullable=False, default=ProposalStatus.DRAFT)
    target_rule_id: Mapped[Optional[int]] = mapped_column(ForeignKey("rules.id"))  # modify/delete

    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[Optional[str]] = mapped_column(String)             # rationale (sanitized markdown)
    proposed_category: Mapped[Optional[str]] = mapped_column(String)
    proposed_text: Mapped[Optional[str]] = mapped_column(String)
    proposed_amount: Mapped[Optional[int]] = mapped_column(Integer)

    voting_opens_at: Mapped[Optional[str]] = mapped_column(String)
    voting_closes_at: Mapped[Optional[str]] = mapped_column(String)
    frozen: Mapped[bool] = mapped_column(Boolean(create_constraint=False), nullable=False, default=False)

    resolved_at: Mapped[Optional[str]] = mapped_column(String)
    resolution_detail: Mapped[Optional[str]] = mapped_column(String)
    merged_rule_id: Mapped[Optional[int]] = mapped_column(ForeignKey("rules.id"))
    merged_rule_version_id: Mapped[Optional[int]] = mapped_column(Integer)  # loose ref (avoids FK cycle)

    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_iso)
    updated_at: Mapped[str] = mapped_column(String, nullable=False, default=now_iso, onupdate=now_iso)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)  # optimistic lock

    votes: Mapped[list["ProposalVote"]] = relationship(
        cascade="all, delete-orphan", lazy="raise_on_sql"
    )
    comments: Mapped[list["ProposalComment"]] = relationship(
        cascade="all, delete-orphan", lazy="raise_on_sql"
    )
    events: Mapped[list["ProposalEvent"]] = relationship(
        cascade="all, delete-orphan", lazy="raise_on_sql"
    )

    __mapper_args__ = {"version_id_col": version}
    __table_args__ = (
        CheckConstraint("type IN ('new_rule', 'modify_rule', 'delete_rule')", name="type_valid"),
        CheckConstraint(
            "status IN ('draft','pending_review','voting','passed','rejected','expired','cancelled')",
            name="status_valid",
        ),
        Index("idx_proposals_status", "status"),
        Index("idx_proposals_proposer", "proposer_id"),
        Index("idx_proposals_closes", "voting_closes_at"),
    )


class ProposalVote(Base):
    """One vote per voter per proposal (yes/no/abstain)."""

    __tablename__ = "proposal_votes"

    id: Mapped[int] = mapped_column(primary_key=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("rule_proposals.id"), nullable=False)
    voter_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    choice: Mapped[str] = mapped_column(String, nullable=False)
    ts: Mapped[str] = mapped_column(String, nullable=False, default=now_iso)

    __table_args__ = (
        UniqueConstraint("proposal_id", "voter_id", name="one_vote_per_voter"),
        CheckConstraint("choice IN ('yes', 'no', 'abstain')", name="choice_valid"),
        Index("idx_pvotes_proposal", "proposal_id"),
    )


class ProposalComment(Base):
    """Discussion on a proposal. Flat for now; `parent_id` reserved for future
    threading. Edits stamp `edited_at`; removals are soft (`deleted`)."""

    __tablename__ = "proposal_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("rule_proposals.id"), nullable=False)
    author_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("proposal_comments.id"))
    body: Mapped[str] = mapped_column(String, nullable=False)
    edited_at: Mapped[Optional[str]] = mapped_column(String)
    deleted: Mapped[bool] = mapped_column(Boolean(create_constraint=False), nullable=False, default=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_iso)

    __table_args__ = (Index("idx_pcomments_proposal", "proposal_id", "created_at"),)


class ProposalEvent(Base):
    """Append-only timeline for a proposal."""

    __tablename__ = "proposal_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("rule_proposals.id"), nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"))  # null = system/sweep
    detail: Mapped[Optional[str]] = mapped_column(String)
    ts: Mapped[str] = mapped_column(String, nullable=False, default=now_iso)

    __table_args__ = (Index("idx_pevents_proposal", "proposal_id", "ts"),)
