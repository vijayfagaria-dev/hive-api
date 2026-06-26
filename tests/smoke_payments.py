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
    assert links["any"].startswith("upi://pay?")
    assert links["gpay"].startswith("tez://upi/pay?")
    assert links["phonepe"].startswith("phonepe://pay?")
    assert links["paytm"].startswith("paytmmp://pay?")
    p = q(links["any"])
    assert p["pa"] == ["hivepot@okhdfcbank"] and p["pn"] == ["Hive Pot"]
    assert p["am"] == ["450.00"] and p["cu"] == ["INR"] and p["tn"] == ["Hive pot - Amit"]
    # spaces -> %20 (not '+'), '@' kept literal in the VPA, '-' unescaped
    assert "pa=hivepot@okhdfcbank" in links["any"]
    assert "Hive%20pot%20-%20Amit" in links["any"]
    print("ok upi links: 4 apps, correct schemes, %20-encoded, literal @")

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
    assert out["total"] == 150
    assert out["upi"]["configured"] and out["upi"]["amount"] == 150
    assert len(out["unpaid"]) == 2 and out["unpaid"][0]["upi"]["amount"] == 50
    assert out["unpaid"][0]["upi"]["links"]["gpay"].startswith("tez://upi/pay?")
    assert "Dishes" in q(out["unpaid"][0]["upi"]["links"]["any"])["tn"][0]
    print("ok pay_out: total + per-fine links + personalized note")

    # unconfigured: still lists the fines, just no pay links
    out0 = pay_out(rows, member, Settings(upi_vpa=""))
    assert out0["total"] == 150 and out0["upi"] == {"configured": False}
    assert out0["unpaid"][0]["upi"] == {"configured": False}
    print("ok pay_out graceful when UPI unset")

    print("\nPAYMENTS SMOKE: ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
