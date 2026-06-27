"""Bill contracts."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class BillBody(BaseModel):
    type: str
    total: int = Field(ge=0)
    month: str = Field(min_length=1)  # 'YYYY-MM'
    # No payer field: the backend always sets paid_by = the authenticated tenant
    # ("I paid this"). Sending a payer from the client is intentionally unsupported.


class DisputeBody(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


def bill_out(row, *, viewer_id: int, now: str) -> dict:
    """A bill card for the dashboard: status + countdown + who claimed it.

    `row` is a recent_bills() Row (bill fields + payer_name + disputer_name). The
    countdown is derived client-side from `confirmDeadline`.
    """
    pending = row.status == "pending"
    can_dispute = (
        pending
        and row.paid_by != viewer_id
        and (row.confirm_deadline is None or row.confirm_deadline > now)
    )
    return {
        "id": row.id,
        "type": row.type,
        "total": row.total,
        "month": row.month,
        "status": row.status,
        "claimedBy": row.payer_name,
        "claimedById": row.paid_by,
        "claimedAt": row.ts,
        "confirmDeadline": row.confirm_deadline,
        "disputedBy": row.disputer_name,
        "disputeReason": row.dispute_reason,
        "resolvedAt": row.resolved_at,
        "canDispute": can_dispute,
    }
