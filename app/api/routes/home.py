"""Home / read views — /me, /dashboard, /spots/<spot>, /public/stats."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_member, get_session, require_login, require_tenant
from app.core.config import settings
from app.core.errors import NotFound
from app.domain.enums import Role
from app.domain.nfc import SPOTS
from app.repositories import members as members_repo
from app.repositories import rules as rules_repo
from app.domain.time import now_iso
from app.schemas.accounts import member_out, self_out
from app.schemas.bills import bill_out
from app.schemas.common import overturn_out
from app.schemas.complaints import recent_complaint_out
from app.schemas.rules import rule_out
from app.services import location, reporting

router = APIRouter(tags=["home"])


@router.get("/me")
async def me(session: AsyncSession = Depends(get_session), member=Depends(require_login)):
    by_category: dict[str, list] = {}
    for rule in await rules_repo.list_all(session):
        by_category.setdefault(rule.category, []).append(rule_out(rule))
    others = [member_out(m) for m in await members_repo.list_active(session) if m.id != member.id]
    return {
        "member": self_out(member),
        "rulesByCategory": by_category,
        "members": others,
        "hallOfShame": await reporting.hall_of_shame(session),
        "gettingHere": location.getting_here_links(settings),
    }


@router.get("/dashboard")
async def dashboard(session: AsyncSession = Depends(get_session), member=Depends(require_tenant)):
    data = await reporting.dashboard(session)
    now_s = now_iso()
    return {
        "pot": data["pot"],
        "potCount": data["pot_count"],
        "dues": data["dues"],
        "recentFines": [recent_complaint_out(f) for f in data["recent"]],
        "overturn": [overturn_out(o) for o in data["overturn"]],
        "bills": [bill_out(b, viewer_id=member.id, now=now_s) for b in data["bills"]],
    }


@router.get("/spots/{spot}")
async def spot(spot: str, session: AsyncSession = Depends(get_session), member=Depends(current_member)):
    config = SPOTS.get(spot)
    if config is None:
        raise NotFound("Unknown spot.")
    if config["category"]:
        rules = await rules_repo.list_by_category(session, config["category"])
    else:
        rules = await rules_repo.list_favorites(session)
    others = [
        member_out(m)
        for m in await members_repo.list_active(session)
        if member is None or m.id != member.id
    ]
    return {
        "spot": spot,
        "config": {
            "emoji": config["emoji"],
            "title": config["title"],
            "category": config["category"],
            "shame": config["shame"],
        },
        "member": self_out(member),
        "isTenant": bool(member and member.role == Role.TENANT),
        "rules": [rule_out(r) for r in rules],
        "members": others,
        "pot": await reporting.pot(session),
        "potCount": await reporting.owed_count(session),
        "hallOfShame": await reporting.hall_of_shame(session) if config["shame"] else [],
    }


@router.get("/public/stats")
async def public_stats(session: AsyncSession = Depends(get_session)):
    return {
        "pot": await reporting.pot(session),
        "potCount": await reporting.owed_count(session),
        "hallOfShame": await reporting.hall_of_shame(session, limit=5),
        # Public so a visitor can get directions to the flat without an account.
        "gettingHere": location.getting_here_links(settings),
    }
