"""JSON API (`/api/*`) consumed by the Next.js frontend.

Mirrors the data behind the (soon-retired) Jinja routes, but returns JSON and
answers with 401/403 instead of redirects. Same session-cookie auth, same
data layer — only the presentation changes. Keys are camelCase for a clean
TypeScript contract (see frontend/src/lib/api.ts).
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from . import auth, fines, location, nfc, queries
from .config import settings

router = APIRouter(prefix="/api")


# --- Auth dependencies (JSON: 401/403, not redirects) ----------------------

async def current_member(request: Request):
    return await auth.current_member(request)


async def require_login(request: Request):
    member = await auth.current_member(request)
    if member is None:
        raise HTTPException(status_code=401, detail="Not logged in.")
    return member


async def require_tenant(request: Request):
    member = await require_login(request)
    if member["role"] != "tenant":
        raise HTTPException(status_code=403, detail="Tenants only.")
    return member


# --- Serializers (Row -> camelCase dict) -----------------------------------

def member_out(m) -> Optional[dict]:
    if m is None:
        return None
    return {"id": m["id"], "name": m["name"], "username": m["username"], "role": m["role"]}


def rule_out(r) -> dict:
    return {
        "id": r["id"],
        "category": r["category"],
        "text": r["text"],
        "amount": r["fine_amount"],
        "isFavorite": bool(r["is_favorite"]),
    }


def recent_fine_out(f) -> dict:
    return {
        "id": f["id"],
        "accused": f["member_name"],
        "accuser": f["accuser_name"],
        "rule": f["rule_text"],
        "amount": f["amount"],
        "status": f["status"],
        "paid": bool(f["paid"]),
        "date": f["ts"][:10],
    }


def overturn_out(o: dict) -> dict:
    return {
        "name": o["name"],
        "filed": o["filed"],
        "upheld": o["upheld"],
        "overturned": o["overturned"],
        "overturnRate": o["overturn_rate"],
    }


# --- Request bodies --------------------------------------------------------

class Credentials(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class ReportBody(BaseModel):
    accusedId: int
    ruleId: int


# --- Auth ------------------------------------------------------------------

@router.get("/auth/me")
async def auth_me(member=Depends(current_member)):
    return {"member": member_out(member)}


@router.post("/auth/register")
async def auth_register(body: Credentials, request: Request):
    username = body.username.strip()
    if len(username) < 3:
        raise HTTPException(422, "Username must be at least 3 characters.")
    if len(body.password) < 6:
        raise HTTPException(422, "Password must be at least 6 characters.")
    db = request.app.state.db
    if await queries.get_member_by_username(db, username) is not None:
        raise HTTPException(409, "That username is taken.")
    try:
        member_id = await queries.register_member(db, username, auth.hash_password(body.password))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "That username is taken.")
    auth.login_member(request, member_id)
    return {"member": member_out(await queries.get_member(db, member_id))}


@router.post("/auth/login")
async def auth_login(body: Credentials, request: Request):
    db = request.app.state.db
    member = await queries.get_member_by_username(db, body.username.strip())
    if member is None or not auth.verify_password(body.password, member["password_hash"]):
        raise HTTPException(401, "Wrong username or password.")
    auth.login_member(request, member["id"])
    return {"member": member_out(member)}


@router.post("/auth/logout")
async def auth_logout(request: Request):
    auth.logout_member(request)
    return {"ok": True}


# --- Hive / home (any logged-in member) ---------------------------------

@router.get("/me")
async def me(request: Request, member=Depends(require_login)):
    db = request.app.state.db
    by_category: dict[str, list] = {}
    for r in await queries.list_all_rules(db):
        by_category.setdefault(r["category"], []).append(rule_out(r))
    others = [
        member_out(m)
        for m in await queries.list_active_members(db)
        if m["id"] != member["id"]
    ]
    return {
        "member": member_out(member),
        "rulesByCategory": by_category,
        "members": others,
        "hallOfShame": await queries.hall_of_shame(db),
        "gettingHere": location.getting_here_links(settings),
    }


# --- Dashboard (tenant only) -----------------------------------------------

@router.get("/dashboard")
async def dashboard(request: Request, member=Depends(require_tenant)):
    db = request.app.state.db
    dues = await queries.all_dues(db)
    overturn = await queries.overturn_stats(db)
    return {
        "pot": await queries.pot_total(db),
        "potCount": await queries.owed_fine_count(db),
        "dues": [d for d in dues if d["total"] > 0],
        "recentFines": [recent_fine_out(f) for f in await queries.recent_fines(db, 15)],
        "overturn": [overturn_out(o) for o in overturn if o["filed"]],
    }


# --- Report / Pay ----------------------------------------------------------

@router.post("/report")
async def report(body: ReportBody, request: Request, member=Depends(require_login)):
    db = request.app.state.db
    try:
        await fines.create_fine(
            db, accused_id=body.accusedId, added_by=member["id"], rule_id=body.ruleId
        )
    except fines.FineError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.get("/pay")
async def pay(request: Request, member=Depends(require_login)):
    db = request.app.state.db
    unpaid = await queries.list_unpaid_owed_fines(db, member["id"])
    return {
        "unpaid": [{"id": f["id"], "amount": f["amount"], "rule": f["rule_text"]} for f in unpaid],
        "walletQr": settings.wallet_upi_qr_url or None,
    }


@router.post("/pay/{fine_id}")
async def pay_fine(fine_id: int, request: Request, member=Depends(require_login)):
    db = request.app.state.db
    fine = await queries.get_fine(db, fine_id)
    if fine is None or fine["member_id"] != member["id"]:
        raise HTTPException(404, "That's not your fine.")
    try:
        changed = await fines.mark_paid(db, fine_id)
    except fines.FineError as e:
        raise HTTPException(400, str(e))
    return {"paid": True, "changed": changed}


# --- NFC spots (public; role decides what the client shows) ----------------

@router.get("/spots/{spot}")
async def spot(spot: str, request: Request, member=Depends(current_member)):
    config = nfc.SPOTS.get(spot)
    if config is None:
        raise HTTPException(404, "Unknown spot.")
    db = request.app.state.db
    if config["category"]:
        rules = await queries.list_rules_by_category(db, config["category"])
    else:
        rules = await queries.list_favorite_rules(db)
    others = [
        member_out(m)
        for m in await queries.list_active_members(db)
        if member is None or m["id"] != member["id"]
    ]
    return {
        "spot": spot,
        "config": {
            "emoji": config["emoji"],
            "title": config["title"],
            "category": config["category"],
            "shame": config["shame"],
        },
        "member": member_out(member),
        "isTenant": bool(member and member["role"] == "tenant"),
        "rules": [rule_out(r) for r in rules],
        "members": others,
        "pot": await queries.pot_total(db),
        "potCount": await queries.owed_fine_count(db),
        "hallOfShame": await queries.hall_of_shame(db) if config["shame"] else [],
    }


# --- Public stats (for the landing — no auth, no sensitive data) ------------

@router.get("/public/stats")
async def public_stats(request: Request):
    db = request.app.state.db
    return {
        "pot": await queries.pot_total(db),
        "potCount": await queries.owed_fine_count(db),
        "hallOfShame": await queries.hall_of_shame(db, limit=5),
    }
