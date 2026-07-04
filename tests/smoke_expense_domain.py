"""Pure-domain smoke test — split strategies + debt simplification.

    .venv/bin/python3 tests/smoke_expense_domain.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.domain.settle import simplify  # noqa: E402
from app.domain.splits import SplitError, compute_splits  # noqa: E402


def owed(strategy, total, pids, params=None):
    return dict(compute_splits(strategy, total, pids, params))


def main():
    P = [1, 2, 3, 4]

    # --- splits: every strategy reconciles to exactly the total ---
    eq = owed("equal", 1000, P)
    assert sum(eq.values()) == 1000 and eq == {1: 250, 2: 250, 3: 250, 4: 250}

    ratio = owed("ratio", 58000, P, {"weights": {1: 27, 2: 27, 3: 27, 4: 19}})
    assert ratio == {1: 15660, 2: 15660, 3: 15660, 4: 11020} and sum(ratio.values()) == 58000

    pct = owed("percentage", 1000, [1, 2], {"pct": {1: 60, 2: 40}})
    assert pct == {1: 600, 2: 400}

    shares = owed("shares", 500, [1, 2, 3], {"shares": {1: 2, 2: 2, 3: 1}})
    assert sum(shares.values()) == 500 and shares == {1: 200, 2: 200, 3: 100}

    fixed = owed("fixed", 900, [1, 2, 3], {"amounts": {1: 500, 2: 300, 3: 100}})
    assert fixed == {1: 500, 2: 300, 3: 100}
    print("ok splits: equal/ratio/percentage/shares/fixed all reconcile to total")

    # weights come from params, not a member column: a guest (no rent share) still splits
    guest = owed("ratio", 300, [9], {"weights": {9: 5}})
    assert guest == {9: 300}

    # --- split validation errors ---
    for bad in (
        ("fixed", 900, [1, 2], {"amounts": {1: 500, 2: 300}}),   # sums to 800, not 900
        ("percentage", 100, [1, 2], {"pct": {1: 60, 2: 30}}),     # sums to 90
        ("equal", 100, [], None),                                 # no participants
        ("bogus", 100, [1], None),                                # unknown strategy
    ):
        try:
            compute_splits(*bad[:3], bad[3]); assert False
        except SplitError:
            pass
    print("ok split validation: non-summing / bad-% / empty / unknown all rejected")

    # --- debt simplification ---
    # The 27/27/27/19 example: A(=1) paid ₹58,000, split by ratio -> A is owed 42,340.
    balances = {1: 42340, 2: -15660, 3: -15660, 4: -11020}
    txns = simplify(balances)
    assert sum(t[2] for t in txns) == 42340
    assert len(txns) == 3 <= len(balances) - 1
    # everyone nets to zero after applying the transfers
    net = dict(balances)
    for frm, to, amt in txns:
        net[frm] += amt
        net[to] -= amt
    assert all(v == 0 for v in net.values())
    # all transfers flow to the sole creditor (member 1)
    assert {t[1] for t in txns} == {1}
    print("ok simplify: 27/27/27/19 settles in 3 transfers, everyone to zero")

    # determinism: same input -> identical output (preview == close)
    assert simplify(balances) == txns

    # a multi-creditor chain: minimal-ish, still reconciles
    b2 = {1: -50, 2: -30, 3: 40, 4: 40}
    t2 = simplify(b2)
    assert len(t2) <= 3
    net2 = dict(b2)
    for frm, to, amt in t2:
        net2[frm] += amt
        net2[to] -= amt
    assert all(v == 0 for v in net2.values())

    # precondition: non-zero sum is rejected (can't invent debt)
    try:
        simplify({1: 10, 2: -5}); assert False
    except ValueError:
        pass
    print("ok simplify: deterministic, multi-creditor reconciles, non-zero sum rejected")

    print("\nEXPENSE DOMAIN SMOKE: ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
