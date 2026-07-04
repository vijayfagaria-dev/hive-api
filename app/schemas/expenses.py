"""Expense + balance contracts — request bodies + response mappers."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ExpenseBody(BaseModel):
    payerId: int
    amount: int = Field(gt=0)
    category: str
    description: Optional[str] = Field(default=None, max_length=200)
    strategy: str = "equal"
    params: Optional[dict] = None          # strategy inputs: {weights|pct|shares|amounts: {memberId: n}}
    participantIds: list[int]
    incurredOn: Optional[str] = None       # 'YYYY-MM-DD'; defaults to today


class ExpenseEditBody(BaseModel):
    amount: int = Field(gt=0)
    category: str
    description: Optional[str] = Field(default=None, max_length=200)
    strategy: str = "equal"
    params: Optional[dict] = None
    participantIds: list[int]


class PaymentBody(BaseModel):
    fromId: int
    toId: Optional[int] = None             # null = paid to the house/landlord
    amount: int = Field(gt=0)
    method: str = "upi"
    note: Optional[str] = Field(default=None, max_length=200)


class SettleBody(BaseModel):
    note: Optional[str] = Field(default=None, max_length=200)


class RentBody(BaseModel):
    memberId: int
    amount: int = Field(gt=0)
    month: str = Field(min_length=7, max_length=7)  # 'YYYY-MM'


class TemplateBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    category: str
    amount: int = Field(gt=0)
    defaultPayerId: Optional[int] = None
    strategy: str = "equal"
    params: Optional[dict] = None
    participantIds: list[int]


class RecurringBody(BaseModel):
    templateId: int
    dayOfMonth: int = Field(ge=1, le=28, default=1)


def template_out(t) -> dict:
    return {
        "id": t.id, "name": t.name, "category": t.category, "amount": t.amount,
        "defaultPayerId": t.default_payer_id, "strategy": t.split_strategy,
        "params": t.split_params, "participantIds": t.participant_ids or [], "active": bool(t.active),
    }


def recurring_out(row) -> dict:
    return {
        "id": row.id, "templateId": row.template_id, "templateName": row.template_name,
        "category": row.category, "amount": row.amount, "dayOfMonth": row.day_of_month,
        "status": row.status, "lastGeneratedMonth": row.last_generated_month,
    }


def expense_out(row) -> dict:
    """A list_expenses() row."""
    return {
        "id": row.id,
        "amount": row.amount,
        "category": row.category,
        "description": row.description,
        "strategy": row.split_strategy,
        "payerId": row.payer_id,
        "payerName": row.payer_name,
        "incurredOn": row.incurred_on,
        "month": row.month,
        "status": row.status,
        "createdAt": row.created_at,
    }


def split_out(row) -> dict:
    return {"memberId": row.member_id, "name": row.member_name, "owed": row.owed_amount}
