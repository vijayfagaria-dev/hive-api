"""Expense + payment data access — the aggregate, its splits/events, and the
per-member balance components (all void-excluded). Balances are derived in the
service by folding these; nothing is stored."""

from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import Row, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models import (
    Expense,
    ExpenseEvent,
    ExpenseSplit,
    ExpenseTemplate,
    Member,
    Payment,
    RecurringExpense,
    SettleRun,
    SettleTxn,
)
from app.domain.enums import ExpenseCategory, ExpenseStatus
from app.repositories import fits_i64

_LIVE = Expense.status != ExpenseStatus.VOID  # every balance query excludes void expenses


# --- expense aggregate ------------------------------------------------------

async def insert_expense(
    session: AsyncSession, *, payer_id: int, amount: int, category: str, description: Optional[str],
    split_strategy: str, split_params: Optional[dict], incurred_on: str, month: str,
    status: str, created_by: Optional[int], recurring_id: Optional[int] = None,
    template_id: Optional[int] = None,
) -> Expense:
    e = Expense(
        payer_id=payer_id, amount=amount, category=category, description=description,
        split_strategy=split_strategy, split_params=split_params, incurred_on=incurred_on,
        month=month, status=status, created_by=created_by,
        recurring_id=recurring_id, template_id=template_id,
    )
    session.add(e)
    await session.flush()
    return e


async def add_split(
    session: AsyncSession, *, expense_id: int, member_id: int, owed_amount: int, weight: Optional[int] = None
) -> ExpenseSplit:
    s = ExpenseSplit(expense_id=expense_id, member_id=member_id, owed_amount=owed_amount, weight=weight)
    session.add(s)
    return s


async def clear_splits(session: AsyncSession, expense_id: int) -> None:
    """Drop an expense's splits (before re-snapshotting them on edit)."""
    await session.execute(delete(ExpenseSplit).where(ExpenseSplit.expense_id == expense_id))


async def get(session: AsyncSession, expense_id) -> Optional[Expense]:
    if not fits_i64(expense_id):
        return None
    return await session.get(Expense, expense_id)


async def log_event(
    session: AsyncSession, *, expense_id: int, type: str, actor_id: Optional[int] = None, detail: Optional[str] = None
) -> ExpenseEvent:
    ev = ExpenseEvent(expense_id=expense_id, type=type, actor_id=actor_id, detail=detail)
    session.add(ev)
    await session.flush()
    return ev


async def list_splits(session: AsyncSession, expense_id: int) -> Sequence[Row]:
    stmt = (
        select(ExpenseSplit.member_id, ExpenseSplit.owed_amount, Member.name.label("member_name"))
        .join(Member, Member.id == ExpenseSplit.member_id)
        .where(ExpenseSplit.expense_id == expense_id)
        .order_by(Member.name)
    )
    return (await session.execute(stmt)).all()


async def list_expenses(
    session: AsyncSession, *, month: Optional[str] = None, category: Optional[str] = None,
    limit: int = 60, include_void: bool = False,
) -> Sequence[Row]:
    payer = aliased(Member)
    stmt = (
        select(
            Expense.id, Expense.amount, Expense.category, Expense.description,
            Expense.split_strategy, Expense.incurred_on, Expense.month, Expense.status,
            Expense.payer_id, payer.name.label("payer_name"), Expense.created_at,
        )
        .join(payer, payer.id == Expense.payer_id)
        .order_by(Expense.incurred_on.desc(), Expense.id.desc())
        .limit(limit)
    )
    if not include_void:
        stmt = stmt.where(_LIVE)  # a deleted expense is out of balances -> keep it out of the feed too
    if month:
        stmt = stmt.where(Expense.month == month)
    if category:
        stmt = stmt.where(Expense.category == category)
    return (await session.execute(stmt)).all()


# --- balance components (per member; void excluded, member<->member only) ----

async def paid_by(session: AsyncSession, member_id: int) -> int:
    """Total a member fronted (credited)."""
    return await session.scalar(
        select(func.coalesce(func.sum(Expense.amount), 0)).where(Expense.payer_id == member_id, _LIVE)
    )


async def owed_by(session: AsyncSession, member_id: int) -> int:
    """Total a member's split shares (debited)."""
    return await session.scalar(
        select(func.coalesce(func.sum(ExpenseSplit.owed_amount), 0))
        .join(Expense, Expense.id == ExpenseSplit.expense_id)
        .where(ExpenseSplit.member_id == member_id, _LIVE)
    )


# --- payments (member<->member only; to_id NULL = house/landlord, excluded) --

async def insert_payment(
    session: AsyncSession, *, from_id: int, to_id: Optional[int], amount: int, method: str,
    purpose: str = "settle", month: Optional[str] = None, note: Optional[str] = None,
    created_by: Optional[int] = None, settle_run_id: Optional[int] = None,
) -> Payment:
    p = Payment(
        from_id=from_id, to_id=to_id, amount=amount, method=method, purpose=purpose, month=month,
        note=note, created_by=created_by, settle_run_id=settle_run_id,
    )
    session.add(p)
    await session.flush()
    return p


async def find_recent_payment_duplicate(
    session: AsyncSession, *, from_id: int, to_id: Optional[int], amount: int, method: str,
    note: Optional[str], since_iso: str,
) -> bool:
    """A same-(from,to,amount,method,note) payment recorded since `since_iso` — used to
    reject accidental double-submits (there's no natural idempotency key on a transfer)."""
    stmt = select(func.count()).select_from(Payment).where(
        Payment.from_id == from_id,
        Payment.to_id.is_(None) if to_id is None else Payment.to_id == to_id,
        Payment.amount == amount,
        Payment.method == method,
        Payment.note.is_(None) if note is None else Payment.note == note,
        Payment.created_at >= since_iso,
    )
    return bool(await session.scalar(stmt))


# --- rent (a shared 'rent'-category expense: fronted by one tenant, split by rent-share,
#     so it ALSO nets in the settle-up graph like any expense — see services/rent.py) ----

async def rent_collected(session: AsyncSession, month: str) -> int:
    """Total rent recorded for a month = the sum of its live rent-category expenses."""
    return await session.scalar(
        select(func.coalesce(func.sum(Expense.amount), 0)).where(
            Expense.category == ExpenseCategory.RENT, Expense.month == month, _LIVE
        )
    )


async def rent_by_member(session: AsyncSession, month: str) -> dict[int, int]:
    """Who fronted how much rent this month (payer_id -> total) — the progress board."""
    rows = await session.execute(
        select(Expense.payer_id, func.coalesce(func.sum(Expense.amount), 0))
        .where(Expense.category == ExpenseCategory.RENT, Expense.month == month, _LIVE)
        .group_by(Expense.payer_id)
    )
    return {mid: total for mid, total in rows.all()}


async def received_by(session: AsyncSession, member_id: int) -> int:
    return await session.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.to_id == member_id)
    )


async def sent_by(session: AsyncSession, member_id: int) -> int:
    """Money a member sent to another member (house/landlord payments excluded)."""
    return await session.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.from_id == member_id, Payment.to_id.is_not(None)
        )
    )


# --- settle-up runs / transactions ------------------------------------------

async def insert_settle_run(session: AsyncSession, *, created_by: Optional[int], note: Optional[str] = None) -> SettleRun:
    run = SettleRun(created_by=created_by, note=note)
    session.add(run)
    await session.flush()
    return run


async def insert_settle_txn(
    session: AsyncSession, *, settle_run_id: int, from_id: int, to_id: int, amount: int
) -> SettleTxn:
    txn = SettleTxn(settle_run_id=settle_run_id, from_id=from_id, to_id=to_id, amount=amount)
    session.add(txn)
    await session.flush()
    return txn


async def get_settle_txn(session: AsyncSession, txn_id) -> Optional[SettleTxn]:
    if not fits_i64(txn_id):
        return None
    return await session.get(SettleTxn, txn_id)


async def list_open_txns(session: AsyncSession) -> Sequence[Row]:
    """Still-proposed transfers with member names — the persisted 'settle up' worklist."""
    frm = aliased(Member)
    to = aliased(Member)
    stmt = (
        select(
            SettleTxn.id, SettleTxn.from_id, frm.name.label("from_name"),
            SettleTxn.to_id, to.name.label("to_name"), SettleTxn.amount,
            SettleTxn.paid_amount, SettleTxn.status,
        )
        .join(frm, frm.id == SettleTxn.from_id)
        .join(to, to.id == SettleTxn.to_id)
        .where(SettleTxn.status == "proposed")
        .order_by(SettleTxn.id.desc())
    )
    return (await session.execute(stmt)).all()


# --- templates + recurring --------------------------------------------------

async def insert_template(
    session: AsyncSession, *, name: str, category: str, amount: int, default_payer_id: Optional[int],
    split_strategy: str, split_params: Optional[dict], participant_ids: list, created_by: Optional[int],
) -> ExpenseTemplate:
    t = ExpenseTemplate(
        name=name, category=category, amount=amount, default_payer_id=default_payer_id,
        split_strategy=split_strategy, split_params=split_params, participant_ids=participant_ids,
        created_by=created_by,
    )
    session.add(t)
    await session.flush()
    return t


async def get_template(session: AsyncSession, template_id) -> Optional[ExpenseTemplate]:
    if not fits_i64(template_id):
        return None
    return await session.get(ExpenseTemplate, template_id)


async def list_templates(session: AsyncSession) -> list[ExpenseTemplate]:
    return list(await session.scalars(
        select(ExpenseTemplate).where(ExpenseTemplate.active.is_(True)).order_by(ExpenseTemplate.name)
    ))


async def insert_recurring(
    session: AsyncSession, *, template_id: int, day_of_month: int, created_by: Optional[int]
) -> RecurringExpense:
    r = RecurringExpense(template_id=template_id, day_of_month=day_of_month, created_by=created_by)
    session.add(r)
    await session.flush()
    return r


async def active_recurrings(session: AsyncSession) -> list[RecurringExpense]:
    return list(await session.scalars(
        select(RecurringExpense).where(RecurringExpense.status == "active").order_by(RecurringExpense.id)
    ))


async def list_recurring(session: AsyncSession) -> Sequence[Row]:
    stmt = (
        select(
            RecurringExpense.id, RecurringExpense.template_id, RecurringExpense.day_of_month,
            RecurringExpense.status, RecurringExpense.last_generated_month,
            ExpenseTemplate.name.label("template_name"), ExpenseTemplate.amount,
            ExpenseTemplate.category,
        )
        .join(ExpenseTemplate, ExpenseTemplate.id == RecurringExpense.template_id)
        .order_by(RecurringExpense.id.desc())
    )
    return (await session.execute(stmt)).all()


async def recurring_generated(session: AsyncSession, recurring_id: int, month: str) -> bool:
    n = await session.scalar(
        select(func.count()).select_from(Expense).where(
            Expense.recurring_id == recurring_id, Expense.month == month
        )
    )
    return bool(n)
