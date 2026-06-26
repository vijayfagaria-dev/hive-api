"""Complaint contracts — request bodies + response mappers."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.domain.enums import PHASE
from app.schemas.accounts import member_out


class DisputeBody(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=280)


class VoteBody(BaseModel):
    vote: str  # 'uphold' | 'void'


def proof_out(proof) -> dict:
    # Upload proofs are served as bytes; telegram proofs live in chat (no url).
    return {
        "id": proof.id,
        "source": proof.source,
        "contentType": proof.content_type,
        "width": proof.width,
        "height": proof.height,
        "url": f"/api/proofs/{proof.id}" if proof.source == "upload" else None,
    }


def event_out(row) -> dict:
    return {"type": row.type, "actor": row.actor_name, "detail": row.detail, "ts": row.ts}


def recent_complaint_out(row) -> dict:
    return {
        "id": row.id,
        "accused": row.member_name,
        "accuser": row.accuser_name,
        "rule": row.rule_text,
        "amount": row.amount,
        "status": row.status,
        "paid": bool(row.paid),
        "date": row.ts[:10],
    }


def detail_out(detail: dict) -> dict:
    """Map the complaints service's assembled view to the API JSON contract."""
    fine = detail["fine"]
    tally = detail["tally"]
    return {
        "id": fine.id,
        "phase": PHASE.get(fine.status, fine.status),
        "status": fine.status,
        "resolution": fine.resolution,
        "accused": member_out(detail["accused"]),
        "accuser": member_out(detail["accuser"]),
        "rule": detail["rule_text"],
        "amount": fine.amount,
        "paid": bool(fine.paid),
        "disputeReason": fine.dispute_reason,
        "coolingDeadline": fine.confirm_deadline,
        "voteDeadline": fine.vote_deadline,
        "proofs": [proof_out(p) for p in detail["proofs"]],
        "timeline": [event_out(e) for e in detail["events"]],
        "vote": {
            "uphold": tally["uphold"],
            "void": tally["void"],
            "eligible": detail["eligible_count"],
            "myVote": detail["my_vote"],
        },
        "canAccept": detail["can_accept"],
        "canDispute": detail["can_dispute"],
        "canVote": detail["can_vote"],
    }
