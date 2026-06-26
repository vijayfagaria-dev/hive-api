"""Bill routes (tenant-only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_tenant
from app.core.errors import NotFound, Unprocessable
from app.domain.enums import BILL_TYPES
from app.repositories import bills as bills_repo
from app.schemas.bills import BillBody
from app.services import billing

router = APIRouter(prefix="/bills", tags=["bills"])


@router.post("")
async def create_bill(
    body: BillBody, session: AsyncSession = Depends(get_session), member=Depends(require_tenant)
):
    if body.type not in BILL_TYPES:
        raise Unprocessable(f"Bill type must be one of {BILL_TYPES}.")
    bill_id = await billing.create_bill(
        session, type=body.type, total=body.total, month=body.month, paid_by=body.paidBy
    )
    return {"ok": True, "billId": bill_id}


@router.post("/{bill_id}/shares/{member_id}/paid")
async def mark_bill_share_paid(
    bill_id: int, member_id: int,
    session: AsyncSession = Depends(get_session), member=Depends(require_tenant),
):
    if await bills_repo.get_bill(session, bill_id) is None:
        raise NotFound("No such bill.")
    await billing.mark_share_paid(session, bill_id, member_id)
    return {"ok": True}
