"""Rule contracts."""

from __future__ import annotations


def rule_out(rule) -> dict:
    return {
        "id": rule.id,
        "category": rule.category,
        "text": rule.text,
        "amount": rule.fine_amount,
        "isFavorite": bool(rule.is_favorite),
    }
