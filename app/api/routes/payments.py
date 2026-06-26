"""Payment routes — pay screen, mark-paid, and the deprecated /report."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_login
from app.core.config import settings
from app.core.errors import DomainError, NotFound
from app.repositories import fines as fines_repo
from app.schemas.payments import pay_out, upi_block
from app.services import complaints

router = APIRouter(tags=["payments"])


@router.get("/pay")
async def pay(session: AsyncSession = Depends(get_session), member=Depends(require_login)):
    unpaid = await fines_repo.list_unpaid_owed(session, member.id)
    return pay_out(unpaid, member, settings)


@router.get("/pay/upi")
async def pay_upi(amount: float | None = None, member=Depends(require_login)):
    """UPI pay block for an arbitrary amount (e.g. top up the pot, or pay nothing-owed)."""
    block = upi_block(settings, amount, f"Hive pot - {member.name}")
    if not block["configured"]:
        raise DomainError("UPI isn't set up yet — ask the flat lead to set UPI_VPA.")
    return block


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
