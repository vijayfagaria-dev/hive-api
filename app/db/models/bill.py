"""Bill aggregate ORM models — a recurring bill and its point-in-time shares.

`bill_shares` is the load-bearing snapshot (DESIGN.md): one row per active tenant
at creation, frozen forever so a later roster change never rewrites a past split.
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
from app.domain.time import now_iso


class Bill(Base):
    __tablename__ = "bills"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String, nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[str] = mapped_column(String, nullable=False)  # 'YYYY-MM'
    paid_by: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"))
    ts: Mapped[str] = mapped_column(String, nullable=False, default=now_iso)

    shares: Mapped[list["BillShare"]] = relationship(
        cascade="all, delete-orphan", lazy="raise_on_sql"
    )

    __table_args__ = (
        CheckConstraint("total >= 0", name="total_non_negative"),
        CheckConstraint(
            "type IN ('rent', 'house_help', 'electricity', 'water')", name="type_valid"
        ),
    )


class BillShare(Base):
    __tablename__ = "bill_shares"

    id: Mapped[int] = mapped_column(primary_key=True)
    bill_id: Mapped[int] = mapped_column(ForeignKey("bills.id"), nullable=False)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    share_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    paid: Mapped[bool] = mapped_column(Boolean(create_constraint=False), nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("bill_id", "member_id", name="one_share_per_member"),
        CheckConstraint("share_amount >= 0", name="share_non_negative"),
        Index("idx_shares_bill", "bill_id"),
        Index("idx_shares_member", "member_id"),
    )
