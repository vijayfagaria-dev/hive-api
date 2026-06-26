"""F6 — Household user management smoke test: permissions, invites, roles, removal.

    .venv/bin/python3 tests/smoke_members.py
"""

import asyncio
import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_PATH"] = os.path.join(tempfile.gettempdir(), f"hive_members_{uuid.uuid4().hex}.db")
os.environ["SECRET_KEY"] = "testsecret"
os.environ["INVITE_MAX_PER_DAY"] = "100"  # don't let the rate-limit block the test
os.environ.pop("TELEGRAM_BOT_TOKEN", None)

from app.core.errors import DomainError  # noqa: E402
from app.db.session import create_all, session_scope  # noqa: E402
from app.domain import permissions  # noqa: E402
from app.repositories import members as members_repo  # noqa: E402
from app.services import accounts  # noqa: E402
from app.services import members as members_svc  # noqa: E402


async def set_role(username: str, role: str):
    async with session_scope() as s:
        m = await members_repo.get_by_username(s, username)
        await accounts.set_role(s, m, role)


async def expire_invite(invitation_id: int):
    from app.repositories import invitations as inv_repo

    async with session_scope() as s:
        inv = await inv_repo.get(s, invitation_id)
        inv.expires_at = "2000-01-01T00:00:00Z"  # in the past


def last_admin_guard():
    async def run():
        # Setup: deactivate every admin except 'owner' (bypassing the service guard).
        async with session_scope() as s:
            owner = await members_repo.get_by_username(s, "owner")
            for m in await members_repo.list_active(s):
                if permissions.can_manage_users(m.role) and m.id != owner.id:
                    m.is_active = False
        # Now 'owner' is the only admin — can't be removed...
        async with session_scope() as s:
            owner = await members_repo.get_by_username(s, "owner")
            try:
                await members_svc.remove(s, actor=owner, member_id=owner.id)
                raise AssertionError("removed the last admin")
            except DomainError:
                pass
        # ...nor demoted out of the admin role.
        async with session_scope() as s:
            owner = await members_repo.get_by_username(s, "owner")
            try:
                await members_svc.change_role(s, actor=owner, member_id=owner.id, role="guest")
                raise AssertionError("demoted the last admin")
            except DomainError:
                pass

    asyncio.run(run())


def main():
    asyncio.run(create_all())
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        # owner self-registers (guest), then is promoted to tenant out-of-band
        owner_id = c.post("/api/auth/register", json={"username": "owner", "password": "ownerpw1"}).json()["member"]["id"]
        asyncio.run(set_role("owner", "tenant"))
        # tess self-registers (guest) — session is now tess
        tess_id = c.post("/api/auth/register", json={"username": "tess", "password": "tesspw12"}).json()["member"]["id"]

        # --- Permission gating: a guest may VIEW but not MANAGE ---
        r = c.get("/api/household/members")
        assert r.status_code == 200 and any(m["username"] == "owner" for m in r.json()["members"])
        assert c.post("/api/household/members/invite", json={"role": "guest"}).status_code == 403
        assert c.delete(f"/api/household/members/{owner_id}").status_code == 403
        assert c.post(f"/api/household/members/{owner_id}/role", json={"role": "guest"}).status_code == 403
        print("ok guest can view the roster but cannot invite / remove / change roles (403)")

        # --- Tenant (admin) role management ---
        c.post("/api/auth/login", json={"username": "owner", "password": "ownerpw1"})
        assert c.post(f"/api/household/members/{tess_id}/role", json={"role": "wizard"}).status_code == 422
        assert c.post("/api/household/members/999999/role", json={"role": "tenant"}).status_code == 404
        promoted = c.post(f"/api/household/members/{tess_id}/role", json={"role": "tenant"})
        assert promoted.status_code == 200 and promoted.json()["member"]["role"] == "tenant"
        detail = c.get(f"/api/household/members/{tess_id}").json()
        assert any(e["type"] == "role_changed" and e["newValue"] == "tenant" for e in detail["events"])
        print("ok promote guest->tenant; invalid role 422; unknown 404; audit event logged")

        # --- Rename + its audit ---
        renamed = c.patch(f"/api/household/members/{tess_id}", json={"name": "Tessa"})
        assert renamed.status_code == 200 and renamed.json()["member"]["name"] == "Tessa"
        assert any(e["type"] == "renamed" for e in c.get(f"/api/household/members/{tess_id}").json()["events"])
        print("ok rename member + audit")

        # --- Invitations: create -> redeem at the invited role ---
        inv = c.post("/api/household/members/invite", json={"role": "guest", "name": "Newbie"}).json()["invitation"]
        assert inv["token"] and inv["status"] == "pending"
        assert len(c.get("/api/household/invites").json()["invitations"]) == 1
        # public preview (no auth needed) shows role + inviter
        prev = c.get(f"/api/household/invites/{inv['token']}").json()
        assert prev["role"] == "guest" and prev["invitedBy"] == "owner"
        # redeem (this registration switches the session to the new member)
        reg = c.post("/api/auth/register", json={"username": "newbie", "password": "newbpw12", "invite": inv["token"]})
        assert reg.status_code == 200 and reg.json()["member"]["role"] == "guest" and reg.json()["member"]["name"] == "Newbie"
        # single-use: reusing the token fails
        assert c.post("/api/auth/register", json={"username": "nb2", "password": "newbpw12", "invite": inv["token"]}).status_code == 400
        print("ok invite redeemed at invited role+name; public preview; single-use (reuse 400)")

        # inviter is notified + the invite is no longer pending
        c.post("/api/auth/login", json={"username": "owner", "password": "ownerpw1"})
        assert any(n["kind"] == "member_invite_accepted" for n in c.get("/api/notifications").json()["notifications"])
        assert len(c.get("/api/household/invites").json()["invitations"]) == 0
        print("ok inviter notified on accept; accepted invite drops out of pending")

        # invite can grant tenant on join
        t2 = c.post("/api/household/members/invite", json={"role": "tenant"}).json()["invitation"]["token"]
        assert c.post("/api/auth/register", json={"username": "cofounder", "password": "cofopw12", "invite": t2}).json()["member"]["role"] == "tenant"
        print("ok invite can grant the tenant role on join")

        # revoke + expiry redemption guards
        c.post("/api/auth/login", json={"username": "owner", "password": "ownerpw1"})
        rinv = c.post("/api/household/members/invite", json={"role": "guest"}).json()["invitation"]
        assert c.post(f"/api/household/invites/{rinv['id']}/revoke").json()["ok"] is True
        assert c.post("/api/auth/register", json={"username": "ghost", "password": "ghostpw1", "invite": rinv["token"]}).status_code == 400
        einv = c.post("/api/household/members/invite", json={"role": "guest"}).json()["invitation"]
        asyncio.run(expire_invite(einv["id"]))
        assert c.post("/api/auth/register", json={"username": "late", "password": "latepw12", "invite": einv["token"]}).status_code == 400
        print("ok revoked + expired invites are rejected on redeem (400)")

        # --- Removal (soft-delete) locks the member out ---
        c.post("/api/auth/login", json={"username": "owner", "password": "ownerpw1"})
        assert c.delete(f"/api/household/members/{tess_id}").status_code == 200  # tess is one of several tenants
        assert not any(m["id"] == tess_id for m in c.get("/api/household/members").json()["members"])
        # a removed member's session no longer authorizes
        c.post("/api/auth/login", json={"username": "tess", "password": "tesspw12"})
        assert c.get("/api/household/members").status_code == 401
        print("ok remove -> soft-deleted, dropped from roster, session no longer authorizes")

        # admin can see departed members with includeInactive
        c.post("/api/auth/login", json={"username": "owner", "password": "ownerpw1"})
        assert any(m["id"] == tess_id and m["isActive"] is False for m in c.get("/api/household/members?includeInactive=true").json()["members"])
        print("ok includeInactive surfaces removed members to admins")

    # --- Last-admin guard (service level) ---
    last_admin_guard()
    print("ok last admin cannot be removed or demoted")

    print("\nF6 MEMBERS SMOKE: ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
