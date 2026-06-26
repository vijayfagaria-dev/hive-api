"""Immutable rule-book history. Rules are never silently overwritten: every
create/modify/delete (via a passed proposal, an admin action, or a rollback)
appends a `rule_versions` snapshot. Rollback = create a new version from an old one.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.time import now_iso


class RuleVersion(Base):
    __tablename__ = "rule_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("rules.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # Snapshot of the rule at this version.
    category: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(String, nullable=False)
    fine_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    is_favorite: Mapped[bool] = mapped_column(Boolean(create_constraint=False), nullable=False, default=False)
    severity_tier: Mapped[str] = mapped_column(String, nullable=False, default="low")
    auto_confirm: Mapped[bool] = mapped_column(Boolean(create_constraint=False), nullable=False, default=True)
    active: Mapped[bool] = mapped_column(Boolean(create_constraint=False), nullable=False, default=True)

    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"))
    approved_by: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"))
    proposal_id: Mapped[Optional[int]] = mapped_column(ForeignKey("rule_proposals.id"))
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_iso)

    __table_args__ = (
        UniqueConstraint("rule_id", "version_number", name="one_version_number_per_rule"),
        Index("idx_ruleversions_rule", "rule_id", "version_number"),
    )
