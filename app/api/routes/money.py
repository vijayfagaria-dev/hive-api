"""Money routes — the per-member statement, the admin ledger, and the settlement.

`/money` is any logged-in member's own statement. Reads of the flat-wide picture
(balances, ledger, settlements) need VIEW_MEMBERS; all mutations need MANAGE_USERS.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_login, require_permission
from app.domain.enums import Permission
from app.repositories import ledger as ledger_repo
from app.schemas.ledger import (
    AdjustBody,
    ChargeBody,
    CreditBody,
    SettleBody,
    ledger_entry_out,
    settlement_out,
)
from app.services import ledger as ledger_svc
from app.services import money, settlements

router = APIRouter(prefix="/money", tags=["money"])


@router.get("")
async def my_money(session: AsyncSession = Depends(get_session), member=Depends(require_login)):
    """The logged-in member's full statement (net + every line behind it)."""
    return await money.statement(session, member)


@router.get("/balances")
async def balances(
    session: AsyncSession = Depends(get_session),
    member=Depends(require_permission(Permission.VIEW_MEMBERS)),
):
    return {"balances": await money.all_balances(session)}


@router.get("/ledger")
async def ledger_list(
    session: AsyncSession = Depends(get_session),
    member=Depends(require_permission(Permission.VIEW_MEMBERS)),
):
    return {"entries": [ledger_entry_out(r) for r in await ledger_repo.list_recent(session)]}


@router.post("/ledger/charge")
async def ledger_charge(
    body: ChargeBody,
    session: AsyncSession = Depends(get_session),
    member=Depends(require_permission(Permission.MANAGE_USERS)),
):
    entries = await ledger_svc.add_charge(
        session, actor=member, type=body.type, total=body.total, reason=body.reason, split=body.split
    )
    return {"ok": True, "count": len(entries)}


@router.post("/ledger/credit")
async def ledger_credit(
    body: CreditBody,
    session: AsyncSession = Depends(get_session),
    member=Depends(require_permission(Permission.MANAGE_USERS)),
):
    entry = await ledger_svc.add_credit(
        session, actor=member, member_id=body.memberId, type=body.type, amount=body.amount, reason=body.reason
    )
    return {"ok": True, "id": entry.id}


@router.post("/ledger/adjust")
async def ledger_adjust(
    body: AdjustBody,
    session: AsyncSession = Depends(get_session),
    member=Depends(require_permission(Permission.MANAGE_USERS)),
):
    entry = await ledger_svc.add_adjustment(
        session, actor=member, member_id=body.memberId, amount=body.amount, reason=body.reason
    )
    return {"ok": True, "id": entry.id}


@router.get("/settlements")
async def settlements_list(
    session: AsyncSession = Depends(get_session),
    member=Depends(require_permission(Permission.VIEW_MEMBERS)),
):
    return {"settlements": [settlement_out(s) for s in await ledger_repo.list_settlements(session)]}


@router.get("/settlement/preview")
async def settlement_preview(
    session: AsyncSession = Depends(get_session),
    member=Depends(require_permission(Permission.MANAGE_USERS)),
):
    return await settlements.preview(session)


@router.post("/settlement/close")
async def settlement_close(
    body: SettleBody,
    session: AsyncSession = Depends(get_session),
    member=Depends(require_permission(Permission.MANAGE_USERS)),
):
    return await settlements.close(session, actor=member, note=body.note)
