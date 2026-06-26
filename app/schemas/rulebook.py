"""Rule-book contracts — the official rules + their immutable version history."""

from __future__ import annotations


def rule_book_out(rule) -> dict:
    return {
        "id": rule.id,
        "category": rule.category,
        "text": rule.text,
        "amount": rule.fine_amount,
        "isFavorite": bool(rule.is_favorite),
        "severityTier": rule.severity_tier,
        "isActive": bool(rule.is_active),
        "useCount": rule.use_count,
    }


def rule_version_out(version) -> dict:
    return {
        "id": version.id,
        "ruleId": version.rule_id,
        "versionNumber": version.version_number,
        "category": version.category,
        "text": version.text,
        "amount": version.fine_amount,
        "isFavorite": bool(version.is_favorite),
        "severityTier": version.severity_tier,
        "active": bool(version.active),
        "createdBy": version.created_by,
        "approvedBy": version.approved_by,
        "proposalId": version.proposal_id,
        "createdAt": version.created_at,
    }
