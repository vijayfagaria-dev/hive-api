"""Expense templates + recurring generation.

A template is a reusable expense definition ("Internet · ₹1,200 · equal · 4 people");
a recurring links one to a monthly cadence. The background sweep generates each month's
expense exactly once — idempotent via the `UNIQUE(recurring_id, month)` constraint plus a
pre-check — mirroring the complaint/bill sweep. `prefill` turns a template into an
editable draft for the one-tap "Generate July Rent" flow.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, Unprocessable
from app.domain.enums import (
    ExpenseCategory,
    ExpenseEventType,
    ExpenseStatus,
    RecurringStatus,
    SplitStrategy,
)
from app.domain.splits import compute_splits
from app.domain.time import now_iso
from app.repositories import expenses as expenses_repo
from app.repositories import members as members_repo
from app.services import notifications

logger = logging.getLogger("hive.recurring")

_CATEGORIES = {c.value for c in ExpenseCategory}
_STRATEGIES = {s.value for s in SplitStrategy}


async def create_template(
    session: AsyncSession, *, actor, name: str, category: str, amount: int,
    default_payer_id: Optional[int], strategy: str, params: Optional[dict], participant_ids: list[int],
) -> int:
    if category not in _CATEGORIES:
        raise Unprocessable(f"Unknown category {category!r}.")
    if strategy not in _STRATEGIES:
        raise Unprocessable(f"Unknown split strategy {strategy!r}.")
    if amount <= 0:
        raise Unprocessable("Amount must be positive.")
    parts = list(dict.fromkeys(participant_ids))
    if not parts:
        raise Unprocessable("Choose at least one participant.")
    compute_splits(strategy, amount, parts, params)  # fail fast on bad split inputs
    t = await expenses_repo.insert_template(
        session, name=name, category=category, amount=amount, default_payer_id=default_payer_id,
        split_strategy=strategy, split_params=params, participant_ids=parts, created_by=actor.id,
    )
    return t.id


async def prefill(session: AsyncSession, template_id: int, month: Optional[str] = None) -> dict:
    t = await expenses_repo.get_template(session, template_id)
    if t is None:
        raise NotFound("No such template.")
    month = month or now_iso()[:7]
    return {
        "payerId": t.default_payer_id, "amount": t.amount, "category": t.category,
        "description": f"{t.name} ({month})", "strategy": t.split_strategy, "params": t.split_params,
        "participantIds": t.participant_ids or [], "incurredOn": f"{month}-01",
    }


async def create_recurring(session: AsyncSession, *, actor, template_id: int, day_of_month: int) -> int:
    if await expenses_repo.get_template(session, template_id) is None:
        raise NotFound("No such template.")
    if not (1 <= day_of_month <= 28):
        raise Unprocessable("Day of month must be between 1 and 28.")
    r = await expenses_repo.insert_recurring(
        session, template_id=template_id, day_of_month=day_of_month, created_by=actor.id
    )
    return r.id


async def sweep_due(session: AsyncSession) -> list[int]:
    """Generate this month's expense for each active recurring (idempotent). Returns ids."""
    month = now_iso()[:7]
    generated: list[int] = []
    for rec in await expenses_repo.active_recurrings(session):
        if await expenses_repo.recurring_generated(session, rec.id, month):
            continue
        t = await expenses_repo.get_template(session, rec.template_id)
        parts = list(t.participant_ids or []) if t else []
        if t is None or not t.active or t.default_payer_id is None or not parts:
            continue
        try:
            owed = compute_splits(t.split_strategy, t.amount, parts, t.split_params)
        except Exception as exc:
            # Never silently skip a broken template (e.g. splits no longer total 100% after a
            # member left). Pause it (so we don't retry-spam every sweep), log loudly, and
            # notify the flat once — a human fixes the template and re-activates it.
            logger.exception("Recurring %s (%s) failed to generate for %s", rec.id, t.name, month)
            rec.status = RecurringStatus.PAUSED
            recipients = await members_repo.list_active_tenants(session)
            if recipients:
                await notifications.recurring_failed(
                    session, recipients=recipients, template_name=t.name, month=month, reason=str(exc),
                )
            continue
        day = min(max(rec.day_of_month, 1), 28)
        exp = await expenses_repo.insert_expense(
            session, payer_id=t.default_payer_id, amount=t.amount, category=t.category,
            description=f"{t.name} ({month})", split_strategy=t.split_strategy, split_params=t.split_params,
            incurred_on=f"{month}-{day:02d}", month=month, status=ExpenseStatus.CONFIRMED,
            created_by=None, recurring_id=rec.id, template_id=t.id,
        )
        for member_id, share in owed:
            await expenses_repo.add_split(session, expense_id=exp.id, member_id=member_id, owed_amount=share)
        await expenses_repo.log_event(
            session, expense_id=exp.id, type=ExpenseEventType.GENERATED, actor_id=None,
            detail=f"auto-generated {t.name} for {month}",
        )
        rec.last_generated_month = month
        payer = await members_repo.get(session, t.default_payer_id)
        recipients = [m for m in await members_repo.list_active(session) if m.id in parts and m.id != t.default_payer_id]
        if payer and recipients:
            await notifications.expense_added(
                session, recipients=recipients, expense_id=exp.id,
                payer_name=payer.name, category=t.category, amount=t.amount,
            )
        generated.append(exp.id)
    return generated
