"""Expense service — create a shared expense with a point-in-time split snapshot.

The payer credit is structural: we only ever record each participant's *owed share*;
the payer's credit for fronting the total is derived in `services/balances.py`. So the
payer is never charged their own share as a debt.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, DomainError, Forbidden, NotFound, Unprocessable
from app.db.models import Member
from app.domain import permissions
from app.domain.enums import (
    ExpenseCategory,
    ExpenseEventType,
    ExpenseStatus,
    PaymentMethod,
    Permission,
    SplitStrategy,
)
from app.domain.splits import compute_splits
from app.domain.time import deadline_iso, now, now_iso
from app.repositories import expenses as expenses_repo
from app.repositories import members as members_repo
from app.services import notifications

_PAYMENT_METHODS = {m.value for m in PaymentMethod}

_CATEGORIES = {c.value for c in ExpenseCategory}
_STRATEGIES = {s.value for s in SplitStrategy}
_WEIGHT_KEY = {"ratio": "weights", "shares": "shares", "percentage": "pct"}


def _weights_snapshot(strategy: str, params: Optional[dict], participant_ids: list[int]) -> dict[int, int]:
    """Freeze each participant's strategy input on their split row (auditable replay)."""
    key = _WEIGHT_KEY.get(strategy)
    if not key or not params:
        return {}
    src = params.get(key) or params.get("percent") or {}
    out: dict[int, int] = {}
    for pid in participant_ids:
        v = src.get(pid, src.get(str(pid)))
        if v is not None:
            out[pid] = int(v)
    return out


async def create_expense(
    session: AsyncSession, *, actor: Member, payer_id: int, amount: int, category: str,
    description: Optional[str], strategy: str, params: Optional[dict],
    participant_ids: list[int], incurred_on: str,
) -> int:
    permissions.require(actor, Permission.CREATE_EXPENSE)
    if category not in _CATEGORIES:
        raise Unprocessable(f"Unknown category {category!r}.")
    if strategy not in _STRATEGIES:
        raise Unprocessable(f"Unknown split strategy {strategy!r}.")
    if amount <= 0:
        raise Unprocessable("Amount must be positive.")

    active = {m.id: m for m in await members_repo.list_active_tenants(session)}
    if payer_id not in active:
        raise Unprocessable("The payer must be an active tenant.")
    parts = list(dict.fromkeys(participant_ids))  # dedupe, preserve order
    if not parts:
        raise Unprocessable("Choose at least one person to share this with.")
    if any(pid not in active for pid in parts):
        raise Unprocessable("Only active tenants can share an expense — guests can only be fined.")

    owed = compute_splits(strategy, amount, parts, params)  # SplitError -> HTTP 400
    weights = _weights_snapshot(strategy, params, parts)

    exp = await expenses_repo.insert_expense(
        session, payer_id=payer_id, amount=amount, category=category, description=description,
        split_strategy=strategy, split_params=params, incurred_on=incurred_on, month=incurred_on[:7],
        status=ExpenseStatus.CONFIRMED, created_by=actor.id,
    )
    for member_id, share in owed:
        await expenses_repo.add_split(
            session, expense_id=exp.id, member_id=member_id, owed_amount=share, weight=weights.get(member_id)
        )
    payer = active[payer_id]
    await expenses_repo.log_event(
        session, expense_id=exp.id, type=ExpenseEventType.CREATED, actor_id=actor.id,
        detail=f"{payer.name} paid ₹{amount} for {category}",
    )
    recipients = [active[pid] for pid in parts if pid != payer_id]
    if recipients:
        await notifications.expense_added(
            session, recipients=recipients, expense_id=exp.id,
            payer_name=payer.name, category=category, amount=amount,
        )
    return exp.id


async def edit_expense(
    session: AsyncSession, *, actor: Member, expense_id: int, amount: int, category: str,
    description: Optional[str], strategy: str, params: Optional[dict], participant_ids: list[int],
) -> None:
    """Re-cost an expense: re-run the strategy, replace the split snapshot, audit it.
    Balances recompute automatically (they're derived); settlement history is preserved."""
    permissions.require(actor, Permission.EDIT_EXPENSE)
    exp = await expenses_repo.get(session, expense_id)
    if exp is None:
        raise NotFound("No such expense.")
    if exp.status == ExpenseStatus.VOID:
        raise DomainError("Can't edit a deleted expense.")
    if category not in _CATEGORIES:
        raise Unprocessable(f"Unknown category {category!r}.")
    if strategy not in _STRATEGIES:
        raise Unprocessable(f"Unknown split strategy {strategy!r}.")
    if amount <= 0:
        raise Unprocessable("Amount must be positive.")
    active = {m.id: m for m in await members_repo.list_active_tenants(session)}
    parts = list(dict.fromkeys(participant_ids))
    if not parts or any(pid not in active for pid in parts):
        raise Unprocessable("Only active tenants can share an expense — guests can only be fined.")

    owed = compute_splits(strategy, amount, parts, params)
    weights = _weights_snapshot(strategy, params, parts)
    exp.amount = amount
    exp.category = category
    exp.description = description
    exp.split_strategy = strategy
    exp.split_params = params
    await expenses_repo.clear_splits(session, exp.id)
    for member_id, share in owed:
        await expenses_repo.add_split(
            session, expense_id=exp.id, member_id=member_id, owed_amount=share, weight=weights.get(member_id)
        )
    await expenses_repo.log_event(
        session, expense_id=exp.id, type=ExpenseEventType.EDITED, actor_id=actor.id,
        detail=f"edited to ₹{amount} for {category}",
    )


async def record_payment(
    session: AsyncSession, *, actor: Member, from_id: int, to_id: Optional[int], amount: int,
    method: str = "upi", note: Optional[str] = None,
):
    """Record a real transfer (settling a member debt, or paying the house/landlord when
    to_id is null). Validated: positive amount, known method, active members, no
    self-payment, and a short-window duplicate guard so a double-submit can't fabricate
    credit (the old route inserted with zero checks — a retry corrupted every balance).
    Tenants only: a guest's fine is paid through the fines flow, never a member transfer."""
    permissions.require(actor, Permission.SETTLE)
    if amount <= 0:
        raise Unprocessable("Amount must be positive.")
    if method not in _PAYMENT_METHODS:
        raise Unprocessable(f"Unknown payment method {method!r}.")
    active = {m.id: m for m in await members_repo.list_active_tenants(session)}
    if from_id not in active:
        raise Unprocessable("The payer must be an active tenant (guests pay fines from the pay screen).")
    if to_id is not None:
        if to_id not in active:
            raise Unprocessable("The payee must be an active tenant.")
        if to_id == from_id:
            raise DomainError("A payment can't be from and to the same person.")
    since = deadline_iso(now(), -1 / 60)  # 60-second double-submit window
    if await expenses_repo.find_recent_payment_duplicate(
        session, from_id=from_id, to_id=to_id, amount=amount, method=method, note=note, since_iso=since
    ):
        raise Conflict("That payment was just recorded — not recording it twice.")
    return await expenses_repo.insert_payment(
        session, from_id=from_id, to_id=to_id, amount=amount, method=method, note=note, created_by=actor.id
    )


async def void_expense(session: AsyncSession, *, actor: Member, expense_id: int) -> None:
    """Soft-delete an expense — it drops out of every balance, its history stays.
    Only the person who paid can delete it."""
    permissions.require(actor, Permission.EDIT_EXPENSE)
    exp = await expenses_repo.get(session, expense_id)
    if exp is None:
        raise NotFound("No such expense.")
    if exp.payer_id != actor.id:
        raise Forbidden("Only the person who paid can delete this expense.")
    if exp.status == ExpenseStatus.VOID:
        raise DomainError("That expense is already deleted.")
    exp.status = ExpenseStatus.VOID
    exp.voided_at = now_iso()
    exp.voided_by = actor.id
    await expenses_repo.log_event(
        session, expense_id=exp.id, type=ExpenseEventType.VOIDED, actor_id=actor.id, detail="deleted"
    )
