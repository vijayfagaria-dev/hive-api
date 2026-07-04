"""Rent — a shared monthly cost, fronted by one tenant and split by rent-share %.

One tenant pays the landlord the whole month's rent; that is recorded as a shared
`Expense` (category='rent', split by each tenant's rent-share %). So — exactly like
groceries or wifi — the payer is credited the full amount and every other tenant owes
their slice, and rent nets together with all other expenses into the single settle-up
number ("send ₹X to Y and everyone's square").

The monthly progress bar (`rent_status`) still shows target vs. what's been fronted; a
month's fronted total must never exceed the ₹58,000 target (over-payment is rejected
with the exact rupee delta). Rent may be fronted in several entries by different tenants.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import DomainError, Unprocessable
from app.domain.enums import ExpenseCategory, SplitStrategy
from app.domain.money import rent_ratio_weights, split_by_ratio
from app.repositories import expenses as expenses_repo
from app.repositories import members as members_repo
from app.services import expenses as expenses_svc


def _targets(tenants) -> list[int]:
    target = settings.monthly_rent
    weights = rent_ratio_weights([t.rent_share_pct or 0 for t in tenants])
    return split_by_ratio(target, weights) if (target and tenants) else [0] * len(tenants)


async def rent_status(session: AsyncSession, month: str) -> dict:
    target = settings.monthly_rent
    tenants = await members_repo.list_active_tenants(session)
    paid_map = await expenses_repo.rent_by_member(session, month)
    per_tenant = [
        {"memberId": t.id, "name": t.name, "target": tgt, "paid": paid_map.get(t.id, 0)}
        for t, tgt in zip(tenants, _targets(tenants))
    ]
    collected = await expenses_repo.rent_collected(session, month)
    return {
        "month": month,
        "target": target,
        "collected": collected,
        "remaining": max(0, target - collected),
        "complete": target > 0 and collected == target,
        "perTenant": per_tenant,
    }


async def record_rent_payment(session: AsyncSession, *, actor, member_id: int, amount: int, month: str) -> dict:
    """One tenant fronts `amount` of the month's rent. Recorded as a shared rent expense
    (split by rent-share %), so the fronter is credited and the others owe their slice —
    it settles through the same peer graph as every other expense."""
    if amount <= 0:
        raise Unprocessable("Amount must be positive.")
    target = settings.monthly_rent
    if target <= 0:
        raise DomainError("Monthly rent isn't configured yet (set MONTHLY_RENT).")
    tenants = await members_repo.list_active_tenants(session)
    if not any(t.id == member_id for t in tenants):
        raise Unprocessable("Rent must be fronted by an active tenant.")
    collected = await expenses_repo.rent_collected(session, month)
    if collected + amount > target:
        over = collected + amount - target
        raise DomainError(
            f"That would push {month} rent to ₹{collected + amount:,} — ₹{over:,} over the ₹{target:,} target."
        )

    # Split the fronted amount across all active tenants by rent-share % (falls back to an
    # even split when shares aren't configured — same rule the targets use).
    weights = rent_ratio_weights([t.rent_share_pct or 0 for t in tenants])
    params = {"weights": {t.id: w for t, w in zip(tenants, weights)}}
    await expenses_svc.create_expense(
        session, actor=actor, payer_id=member_id, amount=amount, category=ExpenseCategory.RENT,
        description=f"Rent {month}", strategy=SplitStrategy.RATIO, params=params,
        participant_ids=[t.id for t in tenants], incurred_on=f"{month}-01",
    )
    new_collected = collected + amount
    return {"ok": True, "collected": new_collected, "remaining": target - new_collected, "complete": new_collected == target}
