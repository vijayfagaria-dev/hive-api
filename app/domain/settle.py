"""Debt simplification — the "fastest way for everyone to get square".

Pure, integer-rupee, no ORM. Greedily settles the largest debtor against the largest
creditor until everyone nets to zero. This yields <= n-1 transfers, which is
*near-minimal* — the true minimum-cash-flow problem is NP-hard, and this is exactly
what Splitwise ships. Deterministic (ties broken by member id) so a preview and the
real run always propose the same transfers.

Hard precondition: the balances must sum to 0. Member↔landlord money is excluded from
the member graph upstream, so the member-only balances always reconcile to zero — this
is what guarantees the simplifier can never invent a phantom debt.
"""

from __future__ import annotations

import heapq


def simplify(balances: dict[int, int]) -> list[tuple[int, int, int]]:
    """Return [(from_id, to_id, amount)] that zeroes every member's balance.

    `balances`: member_id -> net (positive = owed to them, negative = they owe).
    """
    total = sum(balances.values())
    if total != 0:
        raise ValueError(f"balances must sum to 0 to settle (got {total})")

    # Max-heaps by magnitude via negation; tuple compare breaks ties by member id.
    debtors = [(amt, m) for m, amt in balances.items() if amt < 0]   # amt<0; most-negative = largest debt
    creditors = [(-amt, m) for m, amt in balances.items() if amt > 0]  # store -credit; most-negative = largest credit
    heapq.heapify(debtors)
    heapq.heapify(creditors)

    txns: list[tuple[int, int, int]] = []
    while debtors and creditors:
        d_amt, d_id = heapq.heappop(debtors)   # d_amt = -(owe)
        c_amt, c_id = heapq.heappop(creditors)  # c_amt = -(credit)
        owe, credit = -d_amt, -c_amt
        pay = min(owe, credit)
        txns.append((d_id, c_id, pay))
        if owe - pay > 0:
            heapq.heappush(debtors, (-(owe - pay), d_id))
        if credit - pay > 0:
            heapq.heappush(creditors, (-(credit - pay), c_id))
    return txns
