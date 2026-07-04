"""Rent — a landlord-facing monthly obligation (not a member↔member split).

Each tenant's target contribution is their rent-share % of the configured monthly
target (₹58,000); a rent payment is money paid to the house (`Payment` with
`purpose='rent'`, `to_id=NULL`), so it's excluded from the member settle-up graph. The
month's rent may be paid in several entries, but their total must never exceed the
target — over-payment is rejected with the exact rupee delta.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import DomainError, Unprocessable
from app.domain.money import rent_ratio_weights, split_by_ratio
from app.repositories import expenses as expenses_repo
from app.repositories import members as members_repo
from app.services import notifications


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
    if amount <= 0:
        raise Unprocessable("Amount must be positive.")
    target = settings.monthly_rent
    if target <= 0:
        raise DomainError("Monthly rent isn't configured yet (set MONTHLY_RENT).")
    if await members_repo.get(session, member_id) is None:
        raise Unprocessable("No such member.")
    collected = await expenses_repo.rent_collected(session, month)
    if collected + amount > target:
        over = collected + amount - target
        raise DomainError(
            f"That would push {month} rent to ₹{collected + amount:,} — ₹{over:,} over the ₹{target:,} target."
        )

    await expenses_repo.insert_payment(
        session, from_id=member_id, to_id=None, amount=amount, method="upi",
        purpose="rent", month=month, note=f"Rent {month}", created_by=actor.id,
    )
    new_collected = collected + amount
    if new_collected == target:
        recipients = await members_repo.list_active_tenants(session)
        await notifications.rent_completed(session, recipients=recipients, month=month, target=target)
    return {"ok": True, "collected": new_collected, "remaining": target - new_collected, "complete": new_collected == target}
