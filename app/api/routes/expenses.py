"""Expense + balance routes — the Splitwise-style money surface.

Any tenant can add an expense or record a payment; balances are readable by any
logged-in member (transparency). Balances are always derived (services/balances.py).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_login, require_tenant
from app.core.errors import NotFound
from app.domain.time import now_iso
from app.repositories import expenses as expenses_repo
from app.schemas.expenses import (
    ExpenseBody,
    ExpenseEditBody,
    PaymentBody,
    RecurringBody,
    RentBody,
    SettleBody,
    TemplateBody,
    expense_out,
    recurring_out,
    split_out,
    template_out,
)
from app.services import balances, expenses, recurring, rent, settle_up

router = APIRouter(tags=["expenses"])


@router.post("/expenses")
async def create_expense(
    body: ExpenseBody, session: AsyncSession = Depends(get_session), member=Depends(require_tenant)
):
    expense_id = await expenses.create_expense(
        session, actor=member, payer_id=body.payerId, amount=body.amount, category=body.category,
        description=body.description, strategy=body.strategy, params=body.params,
        participant_ids=body.participantIds, incurred_on=body.incurredOn or now_iso()[:10],
    )
    return {"ok": True, "expenseId": expense_id}


@router.get("/expenses")
async def list_expenses(
    month: Optional[str] = None, category: Optional[str] = None,
    session: AsyncSession = Depends(get_session), member=Depends(require_login),
):
    rows = await expenses_repo.list_expenses(session, month=month, category=category)
    return {"expenses": [expense_out(r) for r in rows]}


@router.get("/expenses/{expense_id}")
async def expense_detail(
    expense_id: int, session: AsyncSession = Depends(get_session), member=Depends(require_login)
):
    exp = await expenses_repo.get(session, expense_id)
    if exp is None:
        raise NotFound("No such expense.")
    splits = await expenses_repo.list_splits(session, expense_id)
    return {
        **expense_out_from_model(exp),
        "splits": [split_out(s) for s in splits],
    }


@router.patch("/expenses/{expense_id}")
async def edit_expense(
    expense_id: int, body: ExpenseEditBody,
    session: AsyncSession = Depends(get_session), member=Depends(require_tenant),
):
    await expenses.edit_expense(
        session, actor=member, expense_id=expense_id, amount=body.amount, category=body.category,
        description=body.description, strategy=body.strategy, params=body.params,
        participant_ids=body.participantIds,
    )
    return {"ok": True}


@router.delete("/expenses/{expense_id}")
async def delete_expense(
    expense_id: int, session: AsyncSession = Depends(get_session), member=Depends(require_tenant)
):
    await expenses.void_expense(session, actor=member, expense_id=expense_id)
    return {"ok": True}


@router.post("/payments")
async def record_payment(
    body: PaymentBody, session: AsyncSession = Depends(get_session), member=Depends(require_tenant)
):
    """Record a real transfer (settling a debt, or paying the house/landlord when toId is null)."""
    p = await expenses.record_payment(
        session, actor=member, from_id=body.fromId, to_id=body.toId, amount=body.amount,
        method=body.method, note=body.note,
    )
    return {"ok": True, "paymentId": p.id}


@router.get("/balances")
async def list_balances(session: AsyncSession = Depends(get_session), member=Depends(require_login)):
    return {"balances": await balances.all_balances(session)}


@router.get("/balances/me")
async def my_balance(session: AsyncSession = Depends(get_session), member=Depends(require_login)):
    return await balances.net_for(session, member)


# --- settle up -------------------------------------------------------------

@router.get("/settle/preview")
async def settle_preview(session: AsyncSession = Depends(get_session), member=Depends(require_login)):
    """The near-minimal set of transfers that squares everyone (live; no writes)."""
    return await settle_up.preview(session)


@router.post("/settle")
async def settle_close(
    body: SettleBody, session: AsyncSession = Depends(get_session), member=Depends(require_tenant)
):
    return await settle_up.close(session, actor=member, note=body.note)


@router.post("/settle/txn/{txn_id}/paid")
async def settle_txn_paid(
    txn_id: int, session: AsyncSession = Depends(get_session), member=Depends(require_tenant)
):
    """Record that a proposed transfer actually happened (writes a payment)."""
    return await settle_up.mark_txn_paid(session, actor=member, txn_id=txn_id)


@router.post("/settle/txn/{txn_id}/cancel")
async def settle_txn_cancel(
    txn_id: int, session: AsyncSession = Depends(get_session), member=Depends(require_tenant)
):
    """Cancel a proposed transfer that no longer applies (e.g. paid directly), so it
    doesn't sit 'proposed' forever."""
    return await settle_up.cancel_txn(session, actor=member, txn_id=txn_id)


# --- rent (a shared expense fronted by one tenant; ₹target validated) ------

@router.get("/rent/{month}")
async def rent_status(month: str, session: AsyncSession = Depends(get_session), member=Depends(require_login)):
    """Rent progress for a month: target, collected, remaining, who's fronted what."""
    return await rent.rent_status(session, month)


@router.post("/rent")
async def record_rent(
    body: RentBody, session: AsyncSession = Depends(get_session), member=Depends(require_tenant)
):
    """One tenant fronts (part of) the month's rent — recorded as a shared rent expense that
    nets into settle-up. Rejects anything that pushes the month over the target."""
    return await rent.record_rent_payment(session, actor=member, member_id=body.memberId, amount=body.amount, month=body.month)


# --- templates + recurring -------------------------------------------------

@router.post("/templates")
async def create_template(
    body: TemplateBody, session: AsyncSession = Depends(get_session), member=Depends(require_tenant)
):
    tid = await recurring.create_template(
        session, actor=member, name=body.name, category=body.category, amount=body.amount,
        default_payer_id=body.defaultPayerId, strategy=body.strategy, params=body.params,
        participant_ids=body.participantIds,
    )
    return {"ok": True, "templateId": tid}


@router.get("/templates")
async def list_templates(session: AsyncSession = Depends(get_session), member=Depends(require_login)):
    return {"templates": [template_out(t) for t in await expenses_repo.list_templates(session)]}


@router.get("/templates/{template_id}/prefill")
async def prefill_template(
    template_id: int, month: Optional[str] = None,
    session: AsyncSession = Depends(get_session), member=Depends(require_login),
):
    """An editable draft expense from a template — the 'Generate July Rent' one-tap flow."""
    return await recurring.prefill(session, template_id, month)


@router.post("/recurring")
async def create_recurring(
    body: RecurringBody, session: AsyncSession = Depends(get_session), member=Depends(require_tenant)
):
    rid = await recurring.create_recurring(session, actor=member, template_id=body.templateId, day_of_month=body.dayOfMonth)
    return {"ok": True, "recurringId": rid}


@router.get("/recurring")
async def list_recurring(session: AsyncSession = Depends(get_session), member=Depends(require_login)):
    return {"recurring": [recurring_out(r) for r in await expenses_repo.list_recurring(session)]}


def expense_out_from_model(exp) -> dict:
    return {
        "id": exp.id, "amount": exp.amount, "category": exp.category, "description": exp.description,
        "strategy": exp.split_strategy, "payerId": exp.payer_id, "incurredOn": exp.incurred_on,
        "month": exp.month, "status": exp.status, "createdAt": exp.created_at,
    }
