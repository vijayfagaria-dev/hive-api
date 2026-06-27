"""Money-ledger contracts — request bodies + response mappers."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ChargeBody(BaseModel):
    type: str  # 'broker' | 'deposit'
    total: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=200)
    split: str = "ratio"  # 'ratio' | 'equal'


class CreditBody(BaseModel):
    memberId: int
    type: str = "advance"  # 'advance' | 'deposit' | 'payout'
    amount: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=200)


class AdjustBody(BaseModel):
    memberId: int
    amount: int  # signed, non-zero (+ credit / - debit)
    reason: str = Field(min_length=1, max_length=200)


class SettleBody(BaseModel):
    note: Optional[str] = Field(default=None, max_length=300)


def ledger_entry_out(row) -> dict:
    """A list_recent() row: id, member_id, type, amount, reason, period, created_at, member_name."""
    return {
        "id": row.id,
        "memberId": row.member_id,
        "memberName": row.member_name,
        "type": row.type,
        "amount": row.amount,
        "reason": row.reason,
        "period": row.period,
        "ts": row.created_at,
    }


def settlement_out(s) -> dict:
    return {
        "id": s.id,
        "periodFrom": s.period_from,
        "periodTo": s.period_to,
        "monthlyRent": s.monthly_rent,
        "pot": s.pot_collected,
        "appliedToRent": s.applied_to_rent,
        "leftover": s.leftover,
        "note": s.note,
        "ts": s.created_at,
    }
