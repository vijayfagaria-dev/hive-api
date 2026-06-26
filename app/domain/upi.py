"""UPI payment links — the standard `upi://` intent + per-app deep links.

Pure and transport-free. We only FORMAT a request to pay a payee's own VPA; the
money then moves bank-to-bank inside the payer's UPI app. The app never holds or
moves funds (DESIGN.md — "the wallet is the jar; it only touches read-only").

`any` is the generic `upi://pay?...` intent — also use it as the QR payload, since
every UPI app can scan it. The app-specific links open one chosen app directly;
they are best-effort (Android-first), with the generic link + QR as the universal
fallback.
"""

from __future__ import annotations

from urllib.parse import quote, urlencode

# Same query string, different scheme/host per app.
_SCHEMES: dict[str, str] = {
    "any": "upi://pay",        # generic intent + QR payload
    "gpay": "tez://upi/pay",   # Google Pay (Tez)
    "phonepe": "phonepe://pay",
    "paytm": "paytmmp://pay",
}


def _query(
    vpa: str,
    payee_name: str,
    amount: float | None,
    note: str | None,
    currency: str = "INR",
    txn_ref: str | None = None,
) -> str:
    params: list[tuple[str, str]] = [("pa", vpa), ("pn", payee_name)]
    if amount is not None and amount > 0:
        params.append(("am", f"{amount:.2f}"))
    params.append(("cu", currency))
    if note:
        params.append(("tn", note))
    if txn_ref:
        params.append(("tr", txn_ref))
    # quote (not quote_plus) so spaces encode as %20, never '+'; keep '@' literal in the VPA.
    return urlencode(params, quote_via=quote, safe="@")


def payment_links(
    vpa: str,
    payee_name: str,
    amount: float | None = None,
    note: str | None = None,
    currency: str = "INR",
    txn_ref: str | None = None,
) -> dict[str, str]:
    """`{any, gpay, phonepe, paytm}` deep links for the same payment.

    Pass `links["any"]` to a QR renderer; wire the others to "Pay with <app>" buttons.
    """
    q = _query(vpa, payee_name, amount, note, currency, txn_ref)
    return {app: f"{prefix}?{q}" for app, prefix in _SCHEMES.items()}
