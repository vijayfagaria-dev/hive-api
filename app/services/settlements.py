"""The 2-month settlement — the heart of the agreement's economics.

At close: the fine pot collected since the last settlement is applied toward the
month's rent; any leftover is paid back to tenants by rent ratio (payout credits);
and fines that went unpaid in the period default → a penalty (20% of full rent ×
2 months by default) debited to the defaulter and credited to the others by ratio.

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
from app.domain.money import split_by_ratio
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
    pcts = [t.rent_share_pct or 0 for t in tenants]
    use = pcts if sum(pcts) == 100 else [1] * len(tenants)
    payout_amts = split_by_ratio(leftover, use) if (leftover and tenants) else [0] * len(tenants)
    payouts = [
        {"memberId": t.id, "name": t.name, "amount": amt}
        for t, amt in zip(tenants, payout_amts) if amt
    ]

    penalty_each = round(rent * settings.penalty_rent_pct / 100) * settings.penalty_months
    defaulters = await fines_repo.defaulters_in_period(session, after=after, until=until)
    penalties = []
    for d in defaulters:
        if penalty_each <= 0:
            break
        others = [t for t in tenants if t.id != d.member_id]
        ow = [t.rent_share_pct or 0 for t in others]
        credit_amts = split_by_ratio(penalty_each, ow if sum(ow) > 0 else [1] * len(others)) if others else []
        penalties.append({
            "defaulterId": d.member_id, "defaulterName": d.member_name,
            "unpaid": int(d.owed), "amount": penalty_each,
            "credits": [{"memberId": o.id, "name": o.name, "amount": c}
                        for o, c in zip(others, credit_amts) if c],
        })

    return {
        "periodFrom": after, "periodTo": until, "monthlyRent": rent,
        "pot": pot, "appliedToRent": applied, "leftover": leftover,
        "payouts": payouts, "penalties": penalties,
    }


async def preview(session: AsyncSession) -> dict:
    """Dry-run the settlement (no writes) — for the no-surprises preview screen."""
    return await _compute(session)


async def close(session: AsyncSession, *, actor, note: str | None = None) -> dict:
    """Persist the settlement + its ledger entries, and notify everyone."""
    permissions.require(actor, Permission.MANAGE_USERS)
    c = await _compute(session)
    if not c["pot"] and not c["leftover"] and not c["penalties"]:
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
    for pen in c["penalties"]:
        await ledger_repo.add_entry(
            session, member_id=pen["defaulterId"], type=LedgerEntryType.PENALTY, amount=-pen["amount"],
            reason=f"Unpaid-fine penalty ({label})", period=label, settlement_id=s.id, created_by=actor.id,
        )
        for cr in pen["credits"]:
            await ledger_repo.add_entry(
                session, member_id=cr["memberId"], type=LedgerEntryType.PENALTY, amount=cr["amount"],
                reason=f"Penalty from {pen['defaulterName']} ({label})", period=label,
                settlement_id=s.id, created_by=actor.id,
            )

    from app.services import notifications
    recipients = await members_repo.list_active_tenants(session)
    await notifications.settlement_closed(session, recipients=recipients, period=label,
                                          pot=c["pot"], leftover=c["leftover"])
    return {"settlementId": s.id, **c}
