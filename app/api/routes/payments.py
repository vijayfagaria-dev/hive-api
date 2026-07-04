"""Payment routes — pay screen, mark-paid, and the deprecated /report."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_login
from app.core.config import settings
from app.core.errors import DomainError, NotFound
from app.repositories import fines as fines_repo
from app.schemas.payments import PayFinesBody, pay_out, upi_block
from app.services import complaints

router = APIRouter(tags=["payments"])


@router.get("/pay")
async def pay(session: AsyncSession = Depends(get_session), member=Depends(require_login)):
    unpaid = await fines_repo.list_unpaid_owed(session, member.id)
    return pay_out(unpaid, member, settings)


@router.get("/pay/upi")
async def pay_upi(
    amount: float | None = None,
    fineIds: str | None = None,
    session: AsyncSession = Depends(get_session),
    member=Depends(require_login),
):
    """A UPI block. With `fineIds=1,2` it is bound to exactly those (owned, unpaid) fines —
    the amount is their exact total, never the whole balance (Bug 1). Otherwise it's an
    open/arbitrary-amount block (top up the pot)."""
    if fineIds is not None:
        ids = [int(x) for x in fineIds.split(",") if x.strip().isdigit()]
        if not ids:
            raise DomainError("No valid fine ids provided.")
        fines = await complaints.owed_fines_for(session, member.id, ids)
        total = sum(f.amount for f in fines)
        ref = "HIVEFINES-" + "-".join(str(f.id) for f in fines)
        block = upi_block(settings, total, f"Hive pot - {member.name}", txn_ref=ref, scope="fines")
    else:
        block = upi_block(settings, amount, f"Hive pot - {member.name}", scope="all")
    if not block["configured"]:
        raise DomainError("UPI isn't set up yet — ask the flat lead to set UPI_VPA.")
    return block


@router.post("/pay")
async def pay_fines(
    body: PayFinesBody, session: AsyncSession = Depends(get_session), member=Depends(require_login)
):
    """Settle an explicit set of the caller's fines in one call — each independently.
    Prefer this (or POST /pay/{fine_id}) over paying against a screen-level total."""
    return await complaints.mark_fines_paid(session, member.id, body.fineIds)


@router.post("/pay/{fine_id}")
async def pay_fine(
    fine_id: int, session: AsyncSession = Depends(get_session), member=Depends(require_login)
):
    fine = await fines_repo.get(session, fine_id)
    if fine is None or fine.member_id != member.id:
        raise NotFound("That's not your fine.")
    changed = await complaints.mark_paid(session, fine_id)
    return {"paid": True, "changed": changed}


@router.post("/report")
async def report(member=Depends(require_login)):
    """Deprecated: complaints now require image proof — use POST /api/complaints."""
    raise DomainError(
        "Image proof is now required — POST multipart to /api/complaints instead."
    )
