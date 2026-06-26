"""Payment routes — pay screen, mark-paid, and the deprecated /report."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_login
from app.core.config import settings
from app.core.errors import DomainError, NotFound
from app.repositories import fines as fines_repo
from app.services import complaints

router = APIRouter(tags=["payments"])


@router.get("/pay")
async def pay(session: AsyncSession = Depends(get_session), member=Depends(require_login)):
    unpaid = await fines_repo.list_unpaid_owed(session, member.id)
    return {
        "unpaid": [{"id": r.id, "amount": r.amount, "rule": r.rule_text} for r in unpaid],
        "walletQr": settings.wallet_upi_qr_url or None,
    }


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
