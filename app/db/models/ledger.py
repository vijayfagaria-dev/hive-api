"""Money-ledger ORM models — the per-member balance + the 2-month settlement.

A `LedgerEntry` is a signed amount on one member's running balance (see
`domain.enums.LedgerEntryType`): POSITIVE = credit (the flat owes them / they're
ahead), NEGATIVE = debit (they owe the flat). Rent/bill/fine dues are NOT mirrored
here — they live in their own tables; the money service unifies all of it into one
"My Money" statement. This table holds the one-time + settlement-derived money:
advances, deposit, broker, fine-pot payouts, penalties, and manual adjustments.

A `Settlement` is a closed 2-month period: the fine pot is applied toward the
month's rent and the leftover is paid back by rent ratio (recorded as payout
entries); unpaid fines in the period trigger penalty entries.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.time import now_iso


class Settlement(Base):
    __tablename__ = "settlements"

    id: Mapped[int] = mapped_column(primary_key=True)
    period_from: Mapped[str] = mapped_column(String, nullable=False)  # ISO; exclusive lower bound
    period_to: Mapped[str] = mapped_column(String, nullable=False)    # ISO; inclusive upper bound (close time)
    monthly_rent: Mapped[int] = mapped_column(Integer, nullable=False)  # snapshot of the rent at close
    pot_collected: Mapped[int] = mapped_column(Integer, nullable=False)
    applied_to_rent: Mapped[int] = mapped_column(Integer, nullable=False)
    leftover: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(String)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"))
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_iso)

    __table_args__ = (
        CheckConstraint("pot_collected >= 0", name="pot_non_negative"),
        Index("idx_settlements_to", "period_to"),
    )


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    # Signed rupees: + = credit (flat owes the member), - = debit (member owes the flat).
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    period: Mapped[Optional[str]] = mapped_column(String)  # e.g. 'opening' or a 'YYYY-MM'
    settlement_id: Mapped[Optional[int]] = mapped_column(ForeignKey("settlements.id"))
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"))
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_iso)

    __table_args__ = (
        CheckConstraint(
            "type IN ('advance', 'deposit', 'broker', 'penalty', 'payout', 'adjustment')",
            name="ledger_type_valid",
        ),
        Index("idx_ledger_member", "member_id"),
    )
