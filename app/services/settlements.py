"""The 2-month settlement — the heart of the agreement's economics.

At close: the fine pot collected since the last settlement is applied toward the
month's rent; any leftover is paid back to tenants by rent ratio (payout credits).
(The unpaid-fine penalty was retired — an unpaid fine simply stays owed.)

It only CALCULATES — no money moves. The result is persisted as a Settlement plus
ledger entries, so each member's balance stays the single source of truth. `preview`
runs the same math without writing anything (for the no-surprises preview screen).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import DomainError
from app.domain import permissions
from app.domain.enums import LedgerEntryType, Permission
from app.domain.money import rent_ratio_weights, split_by_ratio
from app.domain.time import now_iso
from app.repositories import fines as fines_repo
from app.repositories import ledger as ledger_repo
from app.repositories import members as members_repo

_EPOCH = "1970-01-01T00:00:00Z"


async def _compute(session: AsyncSession) -> dict:
    last = await ledger_repo.latest_settlement(session)
    after = last.period_to if last else _EPOCH
    until = now_iso()
    rent = settings.monthly_rent

    pot = await fines_repo.paid_pot_in_period(session, after=after, until=until)
    applied = min(pot, rent) if rent > 0 else pot
    leftover = max(0, pot - applied)

    tenants = await members_repo.list_active_tenants(session)
    use = rent_ratio_weights([t.rent_share_pct or 0 for t in tenants])
    payout_amts = split_by_ratio(leftover, use) if (leftover and tenants) else [0] * len(tenants)
    payouts = [
        {"memberId": t.id, "name": t.name, "amount": amt}
        for t, amt in zip(tenants, payout_amts) if amt
    ]

    return {
        "periodFrom": after, "periodTo": until, "monthlyRent": rent,
        "pot": pot, "appliedToRent": applied, "leftover": leftover,
        "payouts": payouts,
    }


async def preview(session: AsyncSession) -> dict:
    """Dry-run the settlement (no writes) — for the no-surprises preview screen."""
    return await _compute(session)


async def close(session: AsyncSession, *, actor, note: str | None = None) -> dict:
    """Persist the settlement + its ledger entries, and notify everyone."""
    permissions.require(actor, Permission.MANAGE_USERS)
    c = await _compute(session)
    if not c["pot"]:
        raise DomainError("Nothing to settle for this period yet.")

    s = await ledger_repo.add_settlement(
        session, period_from=c["periodFrom"], period_to=c["periodTo"], monthly_rent=c["monthlyRent"],
        pot_collected=c["pot"], applied_to_rent=c["appliedToRent"], leftover=c["leftover"],
        note=note, created_by=actor.id,
    )
    label = c["periodTo"][:7]

    for p in c["payouts"]:
        await ledger_repo.add_entry(
            session, member_id=p["memberId"], type=LedgerEntryType.PAYOUT, amount=p["amount"],
            reason=f"Fine-pot leftover ({label})", period=label, settlement_id=s.id, created_by=actor.id,
        )

    from app.services import notifications
    recipients = await members_repo.list_active_tenants(session)
    await notifications.settlement_closed(session, recipients=recipients, period=label,
                                          pot=c["pot"], leftover=c["leftover"])
    return {"settlementId": s.id, **c}
