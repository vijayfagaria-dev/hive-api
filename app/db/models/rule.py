"""Rule ORM model — the house-rules list with self-tuning use_count."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(String, nullable=False)
    fine_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    is_favorite: Mapped[bool] = mapped_column(Boolean(create_constraint=False), nullable=False, default=False)
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    severity_tier: Mapped[str] = mapped_column(String, nullable=False, default="low")
    auto_confirm: Mapped[bool] = mapped_column(Boolean(create_constraint=False), nullable=False, default=True)
    # Severity level 1–5 (L1=₹100 … L5=₹500). Nullable: legacy rules predate it.
    level: Mapped[Optional[int]] = mapped_column(Integer)
    # Who the rule applies to: 'both' | 'tenant' (informational). Nullable for legacy rows.
    applies_to: Mapped[Optional[str]] = mapped_column(String)
    # A "deleted" rule (via a passed delete_rule proposal) is deactivated, never
    # row-deleted, so existing fines that reference it keep their FK + history.
    is_active: Mapped[bool] = mapped_column(Boolean(create_constraint=False), nullable=False, default=True)

    __table_args__ = (
        CheckConstraint("fine_amount >= 0", name="fine_amount_non_negative"),
        CheckConstraint("severity_tier IN ('low', 'high')", name="severity_valid"),
        CheckConstraint("level IS NULL OR level BETWEEN 1 AND 5", name="rule_level_valid"),
        CheckConstraint("applies_to IS NULL OR applies_to IN ('both', 'tenant')", name="rule_applies_to_valid"),
        Index("idx_rules_category", "category"),
    )
