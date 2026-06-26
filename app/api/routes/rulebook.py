"""Rule-book routes — the official rules + immutable version history + rollback."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_login, require_tenant
from app.repositories import rules as rules_repo
from app.schemas.rulebook import rule_book_out, rule_version_out
from app.services import rulebook

router = APIRouter(prefix="/rulebook", tags=["rulebook"])


@router.get("")
async def list_rulebook(
    session: AsyncSession = Depends(get_session), member=Depends(require_login)
):
    rules = await rules_repo.list_all(session)
    return {"rules": [rule_book_out(r) for r in rules]}


@router.get("/{rule_id}/versions")
async def list_versions(
    rule_id: int, session: AsyncSession = Depends(get_session), member=Depends(require_login)
):
    versions = await rulebook.list_versions(session, rule_id)
    return {"versions": [rule_version_out(v) for v in versions]}


@router.post("/{rule_id}/rollback/{version_id}")
async def rollback(
    rule_id: int, version_id: int,
    session: AsyncSession = Depends(get_session), member=Depends(require_tenant),
):
    version = await rulebook.rollback(session, rule_id, version_id, member)
    return {"ok": True, "version": rule_version_out(version)}
