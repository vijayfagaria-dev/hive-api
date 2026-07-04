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


def rent_shares_set(pcts: list[int]) -> bool:
    """True iff explicit rent shares are configured — the per-tenant %s total exactly 100.
    One definition of the rule that was copy-pasted across billing/ledger. WRITES that
    require valid shares (declaring rent, a ratio charge) check this and raise; derived
    READS fall back to an equal split via `rent_ratio_weights`."""
    return sum(pcts) == 100


def rent_ratio_weights(pcts: list[int]) -> list[int]:
    """Weights for a rent-ratio split: the given per-tenant %s if they total exactly 100,
    else an equal split (1 each). The single home for the 'total-100-else-equal' rule that
    settlement payouts and rent targets used to each re-implement."""
    pcts = list(pcts)
    return pcts if rent_shares_set(pcts) else [1] * len(pcts)
