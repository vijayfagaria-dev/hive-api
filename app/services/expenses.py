"""Expense service — create a shared expense with a point-in-time split snapshot.

The payer credit is structural: we only ever record each participant's *owed share*;
the payer's credit for fronting the total is derived in `services/balances.py`. So the
payer is never charged their own share as a debt.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError, NotFound, Unprocessable
from app.db.models import Member
from app.domain.enums import ExpenseCategory, ExpenseEventType, ExpenseStatus, SplitStrategy
from app.domain.splits import compute_splits
from app.domain.time import now_iso
from app.repositories import expenses as expenses_repo
from app.repositories import members as members_repo
from app.services import notifications

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
    if category not in _CATEGORIES:
        raise Unprocessable(f"Unknown category {category!r}.")
    if strategy not in _STRATEGIES:
        raise Unprocessable(f"Unknown split strategy {strategy!r}.")
    if amount <= 0:
        raise Unprocessable("Amount must be positive.")

    active = {m.id: m for m in await members_repo.list_active(session)}
    if payer_id not in active:
        raise Unprocessable("The payer must be an active member.")
    parts = list(dict.fromkeys(participant_ids))  # dedupe, preserve order
    if not parts:
        raise Unprocessable("Choose at least one person to share this with.")
    if any(pid not in active for pid in parts):
        raise Unprocessable("Everyone sharing must be an active member.")

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
    active = {m.id: m for m in await members_repo.list_active(session)}
    parts = list(dict.fromkeys(participant_ids))
    if not parts or any(pid not in active for pid in parts):
        raise Unprocessable("Everyone sharing must be an active member.")

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


async def void_expense(session: AsyncSession, *, actor: Member, expense_id: int) -> None:
    """Soft-delete an expense — it drops out of every balance, its history stays."""
    exp = await expenses_repo.get(session, expense_id)
    if exp is None:
        raise NotFound("No such expense.")
    if exp.status == ExpenseStatus.VOID:
        raise DomainError("That expense is already deleted.")
    exp.status = ExpenseStatus.VOID
    exp.voided_at = now_iso()
    exp.voided_by = actor.id
    await expenses_repo.log_event(
        session, expense_id=exp.id, type=ExpenseEventType.VOIDED, actor_id=actor.id, detail="deleted"
    )
