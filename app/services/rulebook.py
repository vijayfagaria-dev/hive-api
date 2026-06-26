"""Rule-book service — version history + rollback.

Rollback never overwrites history: it copies an old version's snapshot onto the
live rule and appends a *new* version recording the restore.
"""

from __future__ import annotations

from app.core.errors import DomainError, NotFound
from app.repositories import rule_versions as rule_versions_repo
from app.repositories import rules as rules_repo
from sqlalchemy.ext.asyncio import AsyncSession


async def list_versions(session: AsyncSession, rule_id: int):
    if await rules_repo.get(session, rule_id) is None:
        raise NotFound("No such rule.")
    return await rule_versions_repo.list_for(session, rule_id)


async def rollback(session: AsyncSession, rule_id: int, version_id: int, by_member):
    """Restore a rule to a prior version (admin). Returns the new version."""
    rule = await rules_repo.get(session, rule_id)
    if rule is None:
        raise NotFound("No such rule.")
    version = await rule_versions_repo.get(session, version_id)
    if version is None or version.rule_id != rule_id:
        raise DomainError("That version doesn't belong to this rule.")

    rule.category = version.category
    rule.text = version.text
    rule.fine_amount = version.fine_amount
    rule.is_favorite = version.is_favorite
    rule.severity_tier = version.severity_tier
    rule.auto_confirm = version.auto_confirm
    rule.is_active = version.active

    return await rule_versions_repo.insert(
        session,
        rule_id=rule.id,
        version_number=await rule_versions_repo.next_version_number(session, rule.id),
        category=rule.category,
        text=rule.text,
        fine_amount=rule.fine_amount,
        is_favorite=rule.is_favorite,
        severity_tier=rule.severity_tier,
        auto_confirm=rule.auto_confirm,
        active=rule.is_active,
        created_by=by_member.id,
        approved_by=by_member.id,
        proposal_id=None,
    )
