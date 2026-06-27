"""Pure money-split helpers — proportional splits that always reconcile to the total.

No rupee is ever lost: the integer remainder is handed out by the largest-remainder
method, so the parts sum to exactly `total`. With no/zero weights it falls back to an
even split.
"""

from __future__ import annotations


def split_by_ratio(total: int, weights: list[int]) -> list[int]:
    """Split `total` (>= 0) across `weights` proportionally; parts sum to exactly `total`."""
    n = len(weights)
    if n == 0:
        return []
    wsum = sum(weights)
    if wsum <= 0:  # no shares configured -> even split
        base, rem = divmod(total, n)
        return [base + (1 if i < rem else 0) for i in range(n)]
    exact = [total * w / wsum for w in weights]
    floors = [int(x) for x in exact]
    remaining = total - sum(floors)
    # hand the leftover units to the largest fractional parts (largest-remainder method)
    order = sorted(range(n), key=lambda i: exact[i] - floors[i], reverse=True)
    for k in range(remaining):
        floors[order[k]] += 1
    return floors
