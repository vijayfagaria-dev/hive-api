"""Split-strategy registry — the extensibility spine of the expense model.

Every strategy compiles a set of participants + a total into per-participant owed
amounts that sum to *exactly* the total (delegating to `split_by_ratio`, so no rupee
is lost). Adding a new strategy = one function + one registry entry; call sites never
change. Weights/inputs come from the expense's own `params`, never from a member
column, so a tenant with no rent-share can still be a participant.
"""

from __future__ import annotations

from typing import Optional

from app.core.errors import DomainError
from app.domain.money import split_by_ratio


class SplitError(DomainError):
    """Bad split inputs (weights/percentages/amounts) — maps to HTTP 400."""


def _get(mapping: dict, member_id: int, default=None):
    """Look a member up in a params dict whose keys may be ints or JSON strings."""
    if member_id in mapping:
        return mapping[member_id]
    return mapping.get(str(member_id), default)


def _weights_equal(participant_ids: list[int], params: dict) -> list[int]:
    return [1] * len(participant_ids)


def _weights_ratio(participant_ids: list[int], params: dict) -> list[int]:
    weights = params.get("weights") or {}
    out = [int(_get(weights, pid, 0)) for pid in participant_ids]
    if any(w < 0 for w in out):
        raise SplitError("Ratio weights can't be negative.")
    return out


def _weights_shares(participant_ids: list[int], params: dict) -> list[int]:
    shares = params.get("shares") or {}
    out = [int(_get(shares, pid, 0)) for pid in participant_ids]
    if any(w < 0 for w in out):
        raise SplitError("Shares can't be negative.")
    return out


def _weights_percentage(participant_ids: list[int], params: dict) -> list[int]:
    pct = params.get("pct") or params.get("percent") or {}
    out = [int(_get(pct, pid, 0)) for pid in participant_ids]
    if sum(out) != 100:
        raise SplitError(f"Percentages must total 100 (got {sum(out)}).")
    return out


_WEIGHTS = {
    "equal": _weights_equal,
    "ratio": _weights_ratio,
    "shares": _weights_shares,
    "percentage": _weights_percentage,
}
_EXPLICIT = {"fixed", "custom"}


def compute_splits(
    strategy: str,
    total: int,
    participant_ids: list[int],
    params: Optional[dict] = None,
) -> list[tuple[int, int]]:
    """Return [(member_id, owed_amount)] summing to exactly `total`."""
    params = params or {}
    if not participant_ids:
        raise SplitError("An expense needs at least one participant.")
    if total <= 0:
        raise SplitError("Expense amount must be positive.")

    if strategy in _EXPLICIT:
        amounts_in = params.get("amounts") or {}
        amounts = [int(_get(amounts_in, pid, 0)) for pid in participant_ids]
        if any(a < 0 for a in amounts):
            raise SplitError("Split amounts can't be negative.")
        if sum(amounts) != total:
            raise SplitError(f"Split amounts must total ₹{total} (got ₹{sum(amounts)}).")
        return list(zip(participant_ids, amounts))

    builder = _WEIGHTS.get(strategy)
    if builder is None:
        raise SplitError(f"Unknown split strategy: {strategy!r}.")
    weights = builder(participant_ids, params)
    if sum(weights) <= 0:
        raise SplitError("At least one participant must carry a positive share.")
    amounts = split_by_ratio(total, weights)
    return list(zip(participant_ids, amounts))
