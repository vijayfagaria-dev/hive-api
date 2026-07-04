"""Expense aggregate — the unified, Splitwise-style money model.

An `Expense` is one thing a flatmate paid for the group: a `payer`, an `amount`, and a
point-in-time `expense_splits` snapshot (one row per participant with their frozen owed
share). `Payment` rows record money that actually moved. Balances are **derived** from
these facts + the existing ledger/fines — never stored, and the payer is credited the
full amount by construction (so the old "payer still owes their own share" bug can't recur).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain.enums import ExpenseStatus
from app.domain.time import now_iso

_CATEGORIES = "('electricity','water','house_help','internet','gas','cleaner','groceries','brokerage','misc')"
_STRATEGIES = "('equal','ratio','percentage','shares','fixed','custom')"


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    payer_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)  # fronted it → credited the full amount
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String)
    split_strategy: Mapped[str] = mapped_column(String, nullable=False)
    split_params: Mapped[Optional[dict]] = mapped_column(JSON)  # strategy inputs; snapshot for replay/edit
    incurred_on: Mapped[str] = mapped_column(String, nullable=False)  # 'YYYY-MM-DD'
    month: Mapped[str] = mapped_column(String, nullable=False)        # 'YYYY-MM', derived; indexed
    status: Mapped[str] = mapped_column(String, nullable=False, default=ExpenseStatus.CONFIRMED)
    disputed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"))
    dispute_reason: Mapped[Optional[str]] = mapped_column(String)
    recurring_id: Mapped[Optional[int]] = mapped_column(ForeignKey("recurring_expenses.id"))
    template_id: Mapped[Optional[int]] = mapped_column(ForeignKey("expense_templates.id"))
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"))
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_iso)
    resolved_at: Mapped[Optional[str]] = mapped_column(String)
    voided_at: Mapped[Optional[str]] = mapped_column(String)
    voided_by: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"))

    splits: Mapped[list["ExpenseSplit"]] = relationship(cascade="all, delete-orphan", lazy="raise_on_sql")
    events: Mapped[list["ExpenseEvent"]] = relationship(cascade="all, delete-orphan", lazy="raise_on_sql")

    __table_args__ = (
        CheckConstraint("amount > 0", name="expense_amount_positive"),
        CheckConstraint(f"category IN {_CATEGORIES}", name="expense_category_valid"),
        CheckConstraint(f"split_strategy IN {_STRATEGIES}", name="expense_strategy_valid"),
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'disputed', 'void')", name="expense_status_valid"
        ),
        # NULLs compare distinct in SQLite, so many non-recurring (NULL) rows coexist;
        # one recurring instance per month is enforced here (idempotent generation).
        UniqueConstraint("recurring_id", "month", name="one_recurring_per_month"),
        Index("idx_expenses_month", "month", "category"),
        Index("idx_expenses_status", "status"),
        Index("idx_expenses_payer", "payer_id"),
    )


class ExpenseTemplate(Base):
    """A reusable expense definition — 'Internet · ₹1,200 · equal · 4 people'."""

    __tablename__ = "expense_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    default_payer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"))
    split_strategy: Mapped[str] = mapped_column(String, nullable=False)
    split_params: Mapped[Optional[dict]] = mapped_column(JSON)
    participant_ids: Mapped[Optional[list]] = mapped_column(JSON)  # [member_id, ...]
    active: Mapped[bool] = mapped_column(default=True)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"))
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_iso)

    __table_args__ = (CheckConstraint("amount > 0", name="template_amount_positive"),)


class RecurringExpense(Base):
    """A template that auto-generates a monthly expense via the background sweep."""

    __tablename__ = "recurring_expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("expense_templates.id"), nullable=False)
    day_of_month: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    last_generated_month: Mapped[Optional[str]] = mapped_column(String)  # display/optimization only
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"))
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_iso)

    __table_args__ = (
        CheckConstraint("status IN ('active', 'paused', 'ended')", name="recurring_status_valid"),
    )


class ExpenseSplit(Base):
    """One participant's frozen share of an expense (generalized bill_shares)."""

    __tablename__ = "expense_splits"

    id: Mapped[int] = mapped_column(primary_key=True)
    expense_id: Mapped[int] = mapped_column(ForeignKey("expenses.id"), nullable=False)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    owed_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    weight: Mapped[Optional[int]] = mapped_column(Integer)  # snapshotted strategy input, for auditable replay

    __table_args__ = (
        UniqueConstraint("expense_id", "member_id", name="one_split_per_member"),
        CheckConstraint("owed_amount >= 0", name="split_owed_non_negative"),
        Index("idx_splits_expense", "expense_id"),
        Index("idx_splits_member", "member_id"),
    )


class Payment(Base):
    """A real transfer between members (or to the house/landlord when to_id is NULL)."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    from_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    to_id: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"))  # NULL = house/landlord
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str] = mapped_column(String, nullable=False, default="upi")
    # 'settle' = clearing a member debt; 'rent'/'deposit'/'broker' = house/landlord-facing.
    purpose: Mapped[str] = mapped_column(String, nullable=False, default="settle")
    month: Mapped[Optional[str]] = mapped_column(String)  # 'YYYY-MM' for rent, else NULL
    note: Mapped[Optional[str]] = mapped_column(String)
    settle_run_id: Mapped[Optional[int]] = mapped_column(ForeignKey("settle_runs.id"))  # the settle-up run that recorded it
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"))
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_iso)

    __table_args__ = (
        CheckConstraint("amount > 0", name="payment_amount_positive"),
        CheckConstraint("method IN ('upi', 'cash', 'adjustment')", name="payment_method_valid"),
        CheckConstraint(
            "purpose IN ('settle', 'rent', 'deposit', 'broker', 'other')", name="payment_purpose_valid"
        ),
        Index("idx_payments_from", "from_id"),
        Index("idx_payments_to", "to_id"),
        Index("idx_payments_rent", "purpose", "month"),
    )


class SettleRun(Base):
    """One 'settle up' session — a snapshot of the simplified transfers proposed at a
    point in time. The proposed `settle_txns` track which are done; `payments` remain
    the balance source of truth."""

    __tablename__ = "settle_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    note: Mapped[Optional[str]] = mapped_column(String)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"))
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_iso)


class SettleTxn(Base):
    """A single proposed transfer within a settle-up run (from → to)."""

    __tablename__ = "settle_txns"

    id: Mapped[int] = mapped_column(primary_key=True)
    settle_run_id: Mapped[int] = mapped_column(ForeignKey("settle_runs.id"), nullable=False)
    from_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    to_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="proposed")
    payment_id: Mapped[Optional[int]] = mapped_column(ForeignKey("payments.id"))  # the payment that cleared it
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_iso)

    __table_args__ = (
        CheckConstraint("amount > 0", name="settle_txn_amount_positive"),
        CheckConstraint("status IN ('proposed', 'paid', 'cancelled')", name="settle_txn_status_valid"),
        Index("idx_settle_txns_run", "settle_run_id"),
        Index("idx_settle_txns_status", "status"),
    )


class ExpenseEvent(Base):
    """Append-only audit trail for an expense (the bill_events pattern)."""

    __tablename__ = "expense_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    expense_id: Mapped[int] = mapped_column(ForeignKey("expenses.id"), nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"))  # null = system/sweep
    detail: Mapped[Optional[str]] = mapped_column(String)
    ts: Mapped[str] = mapped_column(String, nullable=False, default=now_iso)

    __table_args__ = (Index("idx_expense_events_expense", "expense_id", "ts"),)
