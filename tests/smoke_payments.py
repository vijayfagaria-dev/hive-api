"""UPI pay-links smoke test — pure (no DB).

    .venv/bin/python3 tests/smoke_payments.py

Covers the upi:// + per-app deep-link builder, URL-encoding, the per-fine and
'pay it all' blocks, and graceful degradation when no pot VPA is configured.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import Settings  # noqa: E402
from app.domain import upi  # noqa: E402
from app.schemas.payments import pay_out, upi_block  # noqa: E402


def q(link: str) -> dict:
    return parse_qs(urlsplit(link).query)


def main():
    # --- domain: link building across the four apps ---
    links = upi.payment_links("hivepot@okhdfcbank", "Hive Pot", 450, "Hive pot - Amit")
    assert set(links) == {"any", "gpay", "phonepe", "paytm"}
    # 'any' = the NPCI-standard upi:// intent (also the QR payload).
    assert links["any"].startswith("upi://pay?")
    # Per-app links are Android intent:// launchers (scheme=upi, real packages) — NOT the
    # old vendor schemes (tez://, phonepe://, paytmmp://) that tripped "Insecure payment".
    for app, package in (
        ("gpay", "com.google.android.apps.nbu.paisa.user"),
        ("phonepe", "com.phonepe.app"),
        ("paytm", "net.one97.paytm"),
    ):
        assert links[app].startswith("intent://pay?"), links[app]
        assert "scheme=upi;" in links[app]
        assert f"package={package};" in links[app]
        assert "S.browser_fallback_url=" in links[app]
        assert "upi%3A%2F%2Fpay" in links[app]  # fallback is the canonical upi:// intent
    # No deprecated vendor schemes survive anywhere.
    assert not any(s in "".join(links.values()) for s in ("tez://", "phonepe://pay", "paytmmp://"))
    p = q(links["any"])
    assert p["pa"] == ["hivepot@okhdfcbank"] and p["pn"] == ["Hive Pot"]
    assert p["am"] == ["450.00"] and p["cu"] == ["INR"] and p["tn"] == ["Hive pot - Amit"]
    # spaces -> %20 (not '+'), '@' kept literal in the VPA, '-' unescaped
    assert "pa=hivepot@okhdfcbank" in links["any"]
    assert "Hive%20pot%20-%20Amit" in links["any"]
    print("ok upi links: canonical upi:// + Android intent:// launchers, %20-encoded, literal @")

    # txn_ref (reconciliation) threads into every link as tr=
    reflinks = upi.payment_links("x@y", "Hive", 100, "t", txn_ref="HIVEFINE7")
    assert q(reflinks["any"])["tr"] == ["HIVEFINE7"]
    assert "tr=HIVEFINE7" in reflinks["gpay"]
    print("ok upi txn_ref threads through all links")

    # open amount (None) omits am — payer types the amount
    assert "am=" not in upi.payment_links("x@y", "Hive", None, "t")["any"]
    print("ok open-amount link omits am")

    # --- schema: configured + unconfigured blocks ---
    cfg = Settings(upi_vpa="hivepot@okhdfcbank", upi_payee_name="Hive Pot")
    blk = upi_block(cfg, 100, "Hive pot - Amit")
    assert blk["configured"] and blk["payeeVpa"] == "hivepot@okhdfcbank"
    assert blk["amount"] == 100 and blk["currency"] == "INR"
    assert set(blk["links"]) == {"any", "gpay", "phonepe", "paytm"}
    assert upi_block(Settings(upi_vpa=""), 100, "x") == {"configured": False}
    print("ok upi_block: configured + graceful unconfigured")

    # --- schema: pay_out with fake unpaid rows ---
    member = SimpleNamespace(name="Amit")
    rows = [
        SimpleNamespace(id=1, amount=50, rule_text="Dishes"),
        SimpleNamespace(id=2, amount=100, rule_text="Noise"),
    ]
    out = pay_out(rows, member, cfg)
    assert out["totalOwed"] == 150
    # payAll is the explicit "pay everything" block (scope='all'); the per-fine blocks
    # are scope='fine' — a single-fine payment can never be the whole total (Bug 1).
    assert out["payAll"]["configured"] and out["payAll"]["amount"] == 150 and out["payAll"]["scope"] == "all"
    assert len(out["unpaid"]) == 2 and out["unpaid"][0]["upi"]["amount"] == 50
    assert out["unpaid"][0]["upi"]["scope"] == "fine"
    assert out["unpaid"][0]["upi"]["links"]["gpay"].startswith("intent://pay?")
    assert "Dishes" in q(out["unpaid"][0]["upi"]["links"]["any"])["tn"][0]
    # each fine's link is bound to *that* fine via a distinct txn_ref (per-fine binding)
    assert out["unpaid"][0]["upi"]["txnRef"] == "HIVEFINE1"
    assert q(out["unpaid"][1]["upi"]["links"]["any"])["tr"] == ["HIVEFINE2"]
    assert "total" not in out and "upi" not in out  # deprecated aliases removed
    print("ok pay_out: totalOwed + payAll(scope=all) + per-fine(scope=fine) + txnRef")

    # unconfigured: still lists the fines, just no pay links
    out0 = pay_out(rows, member, Settings(upi_vpa=""))
    assert out0["totalOwed"] == 150 and out0["payAll"] == {"configured": False}
    assert out0["unpaid"][0]["upi"] == {"configured": False}
    print("ok pay_out graceful when UPI unset")

    print("\nPAYMENTS SMOKE: ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
