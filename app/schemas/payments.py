"""Pay-screen contracts — unpaid fines + UPI pay links (scan or app deep-link).

The `upi` block degrades gracefully: `{configured: False}` when no pot VPA is set,
so the frontend can show a "not set up" state (and fall back to `walletQr`).
"""

from __future__ import annotations

from app.domain import upi


def _note(payer_name: str, rule: str | None = None) -> str:
    base = f"Hive pot - {payer_name}"
    return f"{base} ({rule})" if rule else base


def upi_block(settings, amount: float | None, note: str) -> dict:
    """A payable UPI block (payee + amount + the four app links), or unconfigured."""
    if not settings.upi_vpa:
        return {"configured": False}
    return {
        "configured": True,
        "payeeVpa": settings.upi_vpa,
        "payeeName": settings.upi_payee_name,
        "amount": amount,
        "currency": "INR",
        "note": note,
        "links": upi.payment_links(settings.upi_vpa, settings.upi_payee_name, amount, note),
    }


def _fine_out(row, payer_name: str, settings) -> dict:
    return {
        "id": row.id,
        "amount": row.amount,
        "rule": row.rule_text,
        "upi": upi_block(settings, row.amount, _note(payer_name, row.rule_text)),
    }


def pay_out(unpaid, member, settings) -> dict:
    """The pay screen: each unpaid fine (with its own pay link) + a 'pay it all' block."""
    total = sum(r.amount for r in unpaid)
    return {
        "unpaid": [_fine_out(r, member.name, settings) for r in unpaid],
        "total": total,
        "upi": upi_block(settings, total, _note(member.name)),
        "walletQr": settings.wallet_upi_qr_url or None,
    }
