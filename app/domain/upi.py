"""UPI payment links — the NPCI-standard `upi://pay` intent + Android app launchers.

Pure and transport-free. We only FORMAT a request to pay a payee's own VPA; the money
then moves bank-to-bank inside the payer's UPI app. The app never holds or moves funds.

**Why not per-app custom schemes?** The old `tez://`, `phonepe://`, `paytmmp://` vendor
schemes — launched from a *web* origin, to a personal (P2P) VPA, with a pre-filled amount
— trip GPay/PhonePe's "Insecure payment" risk warning. The NPCI-standard `upi://pay`
intent does not: it is exactly the payload the QR carries, which is why *scanning* has
always worked while the app buttons failed. The split was 100% the scheme prefix.

So we emit:

- `any`  = `upi://pay?…`  — the canonical intent + QR payload. Hand it to the OS
  app-chooser and the QR renderer; every UPI app (Android *and* iOS) understands it.
- `gpay` / `phonepe` / `paytm` = Android `intent://` launchers that open one chosen app
  *by package* and fall back to the canonical intent if it isn't installed. This is the
  same transport `services/location.py` already uses correctly for Rapido. iOS cannot use
  `intent://`, so the frontend should render only `any` + the QR (and copy-VPA) on iOS.

`txn_ref` (optional) is threaded through for *reconciliation/attribution* only — it is
**not** part of the risk fix (the working QR path omits it too). A personal P2P VPA always
shows an editable amount and carries mild risk regardless of transport; only a true
merchant VPA yields non-editable pre-filled amounts.
"""

from __future__ import annotations

from urllib.parse import quote, urlencode

# Real Android package names for the app-specific `intent://` launchers.
_PACKAGES: dict[str, str] = {
    "gpay": "com.google.android.apps.nbu.paisa.user",
    "phonepe": "com.phonepe.app",
    "paytm": "net.one97.paytm",
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


def _intent_link(query: str, package: str, fallback: str) -> str:
    """An Android `intent://` launcher for one UPI app: targets it by `package`, declares
    `scheme=upi`, and falls back to the canonical `upi://` intent (thence the OS chooser)
    if the app isn't installed. Mirrors the Rapido launcher in services/location.py."""
    return (
        f"intent://pay?{query}"
        f"#Intent;scheme=upi;package={package};"
        f"S.browser_fallback_url={quote(fallback, safe='')};end"
    )


def payment_links(
    vpa: str,
    payee_name: str,
    amount: float | None = None,
    note: str | None = None,
    currency: str = "INR",
    txn_ref: str | None = None,
) -> dict[str, str]:
    """`{any, gpay, phonepe, paytm}` links for the same payment.

    `any` is the NPCI-standard `upi://pay` intent — pass it to the QR renderer and the OS
    app-chooser. `gpay`/`phonepe`/`paytm` are Android `intent://` launchers for one app
    each; on iOS render only `any` + the QR (intent:// is Android-only). Keys are stable;
    only the values changed from the (rejected) vendor schemes.
    """
    q = _query(vpa, payee_name, amount, note, currency, txn_ref)
    canonical = f"upi://pay?{q}"
    links = {"any": canonical}
    for app, package in _PACKAGES.items():
        links[app] = _intent_link(q, package, canonical)
    return links
