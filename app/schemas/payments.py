"""Pay-screen contracts — unpaid fines + UPI pay links (scan or app deep-link).

The `upi` block degrades gracefully: `{configured: False}` when no pot VPA is set,
so the frontend can show a "not set up" state (and fall back to `walletQr`).
"""

from __future__ import annotations

from pydantic import BaseModel

from app.domain import upi


class PayFinesBody(BaseModel):
    """Settle an explicit set of fines — the caller names exactly which fines a payment
    covers, so a single-fine payment can never be conflated with the whole balance."""

    fineIds: list[int]


def _note(payer_name: str, rule: str | None = None) -> str:
    base = f"Hive pot - {payer_name}"
    return f"{base} ({rule})" if rule else base


def upi_block(
    settings, amount: float | None, note: str, txn_ref: str | None = None, scope: str | None = None
) -> dict:
    """A payable UPI block (payee + amount + the app links), or unconfigured. `scope`
    ('fine' | 'fines' | 'all') tells the frontend exactly what this link settles, so a
    per-fine payable is never confused with the pay-everything aggregate (Bug 1).
    `txn_ref` is threaded into the links for reconciliation."""
    if not settings.upi_vpa:
        return {"configured": False}
    return {
        "configured": True,
        "scope": scope,
        "payeeVpa": settings.upi_vpa,
        "payeeName": settings.upi_payee_name,
        "amount": amount,
        "currency": "INR",
        "note": note,
        "txnRef": txn_ref,
        "links": upi.payment_links(
            settings.upi_vpa, settings.upi_payee_name, amount, note, txn_ref=txn_ref
        ),
    }


def _fine_out(row, payer_name: str, settings) -> dict:
    return {
        "id": row.id,
        "amount": row.amount,
        "rule": row.rule_text,
        # Each fine's link carries its own reference + scope='fine', so a payment can be
        # reconciled to exactly this fine (the per-fine binding the pay screen needs — Bug 1).
        "upi": upi_block(
            settings, row.amount, _note(payer_name, row.rule_text),
            txn_ref=f"HIVEFINE{row.id}", scope="fine",
        ),
    }


def pay_out(unpaid, member, settings) -> dict:
    """The pay screen. `unpaid[i].upi` is the payable for one specific fine (scope='fine').
    `totalOwed` is a DISPLAY figure; `payAll` is an explicit pay-everything payable
    (scope='all') the user chooses deliberately — it is NOT a peer of the per-fine blocks,
    so selecting one fine can't silently pay the whole balance (Bug 1)."""
    total = sum(r.amount for r in unpaid)
    ref_all = "HIVEFINES-" + "-".join(str(r.id) for r in unpaid) if unpaid else None
    pay_all = upi_block(settings, total, _note(member.name), txn_ref=ref_all, scope="all")
    return {
        "unpaid": [_fine_out(r, member.name, settings) for r in unpaid],
        "totalOwed": total,
        "payAll": pay_all,
        "walletQr": settings.wallet_upi_qr_url or None,
    }
