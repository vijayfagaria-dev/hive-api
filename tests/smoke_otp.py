"""Auth hardening smoke test — email OTP signup, forgot password, email change,
session revocation, login lockout, password policy, rate limiting, templates.

    .venv/bin/python3 tests/smoke_otp.py
"""

import asyncio
import base64
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_PATH"] = os.path.join(tempfile.gettempdir(), f"hive_otp_{uuid.uuid4().hex}.db")
os.environ["SECRET_KEY"] = "testsecret"
os.environ["APP_BASE_URL"] = "https://hive.test"
os.environ.pop("SMTP_HOST", None)

from itsdangerous import TimestampSigner  # noqa: E402
from sqlalchemy import select, update  # noqa: E402

from app.core import ratelimit, security  # noqa: E402
from app.db.models import Member, OtpChallenge  # noqa: E402
from app.db.session import create_all, session_scope  # noqa: E402
from app.domain import passwords  # noqa: E402
from app.domain.time import now, shift_iso  # noqa: E402
from app.infra import email_templates  # noqa: E402
from app.repositories import members as members_repo  # noqa: E402
from app.services import otp  # noqa: E402
from mailbox import Mailbox, signup  # noqa: E402

_ip = 0


def fresh_ip() -> dict:
    """A distinct client IP per scenario, so the per-IP throttle only bites where tested."""
    global _ip
    _ip += 1
    return {"X-Forwarded-For": f"203.0.113.{_ip}"}


def db(coro_fn):
    async def run():
        async with session_scope() as s:
            return await coro_fn(s)
    return asyncio.run(run())


def challenge(email: str, purpose: str = "register") -> OtpChallenge:
    async def q(s):
        return await s.scalar(
            select(OtpChallenge)
            .where(OtpChallenge.email == email, OtpChallenge.purpose == purpose)
            .order_by(OtpChallenge.id.desc())
        )
    return db(q)


def age_challenge(email: str, purpose: str = "register", *, sent_ago: int = 0, expire: bool = False) -> None:
    async def q(s):
        values = {"last_sent_at": shift_iso(now(), -sent_ago)}
        if expire:
            values["expires_at"] = shift_iso(now(), -1)
        await s.execute(
            update(OtpChallenge)
            .where(OtpChallenge.email == email, OtpChallenge.purpose == purpose, OtpChallenge.consumed_at.is_(None))
            .values(**values)
        )
    db(q)


def member(username: str) -> Member:
    return db(lambda s: members_repo.get_by_username(s, username))


# --- Pure units ----------------------------------------------------------------

def unit_checks():
    code = security.generate_otp()
    assert len(code) == 6 and code.isdigit()
    h = security.hash_otp("register", "a@b.co", code)
    assert code not in h and len(h) == 64
    assert security.verify_otp("register", "a@b.co", code, h)
    assert not security.verify_otp("password_reset", "a@b.co", code, h), "digest is purpose-bound"
    assert not security.verify_otp("register", "x@b.co", code, h), "digest is address-bound"
    print("ok OTP: 6 digits, stored as keyed digest bound to purpose + address")

    p = lambda pw, u=None: passwords.problems(pw, username=u, min_length=8)  # noqa: E731
    assert p("short1")[0].startswith("Password must be at least 8")
    assert "too common" in p("password123")[0]
    assert "repeated" in p("aaaaaaaaaa")[0]
    assert "username" in p("zoe-rocks-1", "zoe")[0]
    assert "72 bytes" in p("é" * 40)[0]  # 80 bytes of UTF-8 — bcrypt>=5 would raise
    assert p("lime-tree-41", "zoe") == []
    print("ok password policy: length, 72-byte cap, common list, repeats, username")

    msg = email_templates.otp_email(
        purpose="register", to="z@example.com", code="123456", minutes=10, username="<b>zoe</b>"
    )
    assert msg.subject == "123456 is your Hive verification code"
    assert "123 456" in msg.html and "123 456" in msg.text and "10 minutes" in msg.text
    assert "<b>zoe</b>" not in msg.html and "&lt;b&gt;zoe&lt;/b&gt;" in msg.html, "username is escaped"
    reset = email_templates.otp_email(purpose="password_reset", to="z@example.com", code="654321", minutes=10)
    assert "reset" in reset.subject and "654 321" in reset.html
    notice = email_templates.password_changed_email(to="z@example.com", username="zoe", how="reset")
    assert notice.subject == "Your Hive password was reset" and "https://hive.test/forgot-password" in notice.html
    print("ok email templates: code + expiry rendered, HTML-escaped, plain-text twin, reset link")


# --- API flows ---------------------------------------------------------------

def signup_checks(c, box):
    h = fresh_ip()
    body = {"username": "zoe", "password": "lime-tree-41", "email": "Zoe@Example.com"}
    r = c.post("/api/auth/register", json=body, headers=h)
    assert r.status_code == 200, r.text
    v = r.json()["verification"]
    assert v["email"] == "zoe@example.com" and 590 <= v["expiresIn"] <= 600 and 55 <= v["resendIn"] <= 60
    assert c.get("/api/auth/me").json()["member"] is None, "no session before verification"
    assert member("zoe") is None, "no member row before verification"
    code = box.code_for("zoe@example.com")
    ch = challenge("zoe@example.com")
    assert code not in ch.code_hash and ch.password_hash.startswith("$2b$") and "lime" not in ch.password_hash
    print("ok register mails a code; no account/session until verified; nothing stored in plaintext")

    # double-submit inside the cooldown: no second email, same challenge
    assert c.post("/api/auth/register", json=body, headers=h).status_code == 200
    assert box.count_to("zoe@example.com") == 1 and challenge("zoe@example.com").id == ch.id
    print("ok re-submitting inside the cooldown reuses the challenge (no extra mail)")

    wrong = "000000" if code != "000000" else "111111"
    r = c.post("/api/auth/register/verify", json={"email": "zoe@example.com", "code": wrong}, headers=h)
    assert r.status_code == 400 and "4 attempts left" in r.json()["detail"]
    assert challenge("zoe@example.com").attempts == 1, "wrong guess persisted despite the 400"
    assert c.post("/api/auth/register/verify", json={"email": "zoe@example.com", "code": "12ab"}, headers=h).status_code == 400
    assert challenge("zoe@example.com").attempts == 1, "malformed input doesn't burn an attempt"
    print("ok wrong code -> 400 with attempts left (persisted); malformed code not counted")

    r = c.post("/api/auth/register/resend", json={"email": "zoe@example.com"}, headers=h)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    print("ok resend inside the cooldown -> 429 + Retry-After")

    r = c.post("/api/auth/register/verify", json={"email": "zoe@example.com", "code": code[:3] + " " + code[3:]}, headers=h)
    assert r.status_code == 200, r.text
    me = r.json()["member"]
    assert me["role"] == "guest" and me["email"] == "zoe@example.com" and me["emailVerified"] is True
    assert c.get("/api/auth/me").json()["member"]["username"] == "zoe"
    events = db(lambda s: __import__("app.repositories.member_events", fromlist=["x"]).list_for(s, me["id"]))
    assert [e.type for e in events] == ["joined"]
    print("ok correct code -> member created (email verified) + logged in + 'joined' audit")

    r = c.post("/api/auth/register/verify", json={"email": "zoe@example.com", "code": code}, headers=h)
    assert r.status_code == 400, "codes are one-time"
    print("ok a used code can't be replayed")

    taken = {"username": "zoe2", "password": "lime-tree-41", "email": "ZOE@example.com"}
    assert c.post("/api/auth/register", json=taken, headers=h).status_code == 409
    long_pw = {"username": "lena", "password": "é" * 40, "email": "lena@example.com"}
    assert c.post("/api/auth/register", json=long_pw, headers=h).status_code == 422, "no bcrypt 500"
    weak = {"username": "lena", "password": "password1", "email": "lena@example.com"}
    assert c.post("/api/auth/register", json=weak, headers=h).status_code == 422
    assert c.post("/api/auth/register", json={**weak, "password": "x-lena-pw", "email": "nope"}, headers=h).status_code == 422
    print("ok signup rejects taken email (409), weak/oversized passwords + bad email (422)")


def expiry_attempts_resend_checks(c, box):
    h = fresh_ip()
    c.post("/api/auth/logout")
    body = {"username": "kai", "password": "harbor-lights-9", "email": "kai@example.com"}
    assert c.post("/api/auth/register", json=body, headers=h).status_code == 200
    first = box.code_for("kai@example.com")

    age_challenge("kai@example.com", expire=True)
    r = c.post("/api/auth/register/verify", json={"email": "kai@example.com", "code": first}, headers=h)
    assert r.status_code == 400 and "expired" in r.json()["detail"]
    print("ok expired code -> 400 'expired'")

    age_challenge("kai@example.com", sent_ago=61)
    r = c.post("/api/auth/register/resend", json={"email": "kai@example.com"}, headers=h)
    assert r.status_code == 200 and r.json()["verification"]["resendIn"] >= 55
    second = box.code_for("kai@example.com", count=2)
    ch = challenge("kai@example.com")
    assert ch.send_count == 2 and ch.attempts == 0 and ch.expires_at > shift_iso(now(), 500)
    print("ok resend after cooldown rotates the code with a fresh expiry")

    wrong = "000000" if second != "000000" else "111111"
    for i in range(4):
        r = c.post("/api/auth/register/verify", json={"email": "kai@example.com", "code": wrong}, headers=h)
        assert r.status_code == 400
    r = c.post("/api/auth/register/verify", json={"email": "kai@example.com", "code": wrong}, headers=h)
    assert r.status_code == 429, "5th wrong guess locks the code"
    r = c.post("/api/auth/register/verify", json={"email": "kai@example.com", "code": second}, headers=h)
    assert r.status_code == 429, "even the right code is refused once attempts are exhausted"
    print("ok attempt limit: 5 wrong guesses lock the code (even the right one is refused)")

    # a fresh code unlocks the flow again
    age_challenge("kai@example.com", sent_ago=61)
    assert c.post("/api/auth/register/resend", json={"email": "kai@example.com"}, headers=h).status_code == 200
    third = box.code_for("kai@example.com", count=3)
    r = c.post("/api/auth/register/verify", json={"email": "kai@example.com", "code": third}, headers=h)
    assert r.status_code == 200, r.text
    print("ok a new code after lockout completes signup")

    # hourly cap on sends per address
    body = {"username": "max", "password": "violet-hour-22", "email": "max@example.com"}
    assert c.post("/api/auth/register", json=body, headers=h).status_code == 200
    for _ in range(4):
        age_challenge("max@example.com", sent_ago=61)
        assert c.post("/api/auth/register/resend", json={"email": "max@example.com"}, headers=h).status_code == 200
    age_challenge("max@example.com", sent_ago=61)
    r = c.post("/api/auth/register/resend", json={"email": "max@example.com"}, headers=h)
    assert r.status_code == 429 and "hour" in r.json()["detail"]
    print("ok hourly cap: 6th code to one address in an hour -> 429")

    assert c.post("/api/auth/register/resend", json={"email": "ghost@example.com"}, headers=h).status_code == 400
    print("ok resend with no pending signup -> 400")


def forgot_password_checks(c, box):
    h = fresh_ip()
    # A second device logged in as zoe — the reset must sign it out.
    from fastapi.testclient import TestClient
    from app.main import app
    other = TestClient(app)
    assert other.post("/api/auth/login", json={"username": "zoe", "password": "lime-tree-41"}, headers=h).status_code == 200
    assert other.get("/api/auth/me").json()["member"]["username"] == "zoe"

    unknown = c.post("/api/auth/password/forgot", json={"email": "nobody@example.com"}, headers=h)
    known = c.post("/api/auth/password/forgot", json={"email": "zoe@example.com"}, headers=h)
    assert unknown.status_code == known.status_code == 200
    assert set(unknown.json()["verification"]) == set(known.json()["verification"])
    assert box.count_to("nobody@example.com") == 0
    code = box.code_for("zoe@example.com", count=2)  # #1 was the signup code
    assert "reset" in box.wait_for("zoe@example.com", count=2).subject
    print("ok forgot: identical response for unknown vs known email; only the real one is mailed")

    r = c.post("/api/auth/password/verify", json={"email": "nobody@example.com", "code": code}, headers=h)
    assert r.status_code == 400, "decoy challenge never verifies"
    wrong = "000000" if code != "000000" else "111111"
    assert c.post("/api/auth/password/verify", json={"email": "zoe@example.com", "code": wrong}, headers=h).status_code == 400
    r = c.post("/api/auth/password/verify", json={"email": "zoe@example.com", "code": code}, headers=h)
    assert r.status_code == 200 and r.json()["resetToken"] and r.json()["expiresIn"] == 15 * 60
    token = r.json()["resetToken"]
    assert c.post("/api/auth/password/verify", json={"email": "zoe@example.com", "code": code}, headers=h).status_code == 400
    print("ok reset code -> single-use reset token (code can't be re-verified)")

    r = c.post("/api/auth/password/reset", json={"resetToken": token, "newPassword": "short"}, headers=h)
    assert r.status_code == 422
    r = c.post("/api/auth/password/reset", json={"resetToken": token, "newPassword": "new-dawn-2026"}, headers=h)
    assert r.status_code == 200 and r.json()["member"]["username"] == "zoe"
    assert c.get("/api/auth/me").json()["member"]["username"] == "zoe", "reset logs this device in"
    assert other.get("/api/auth/me").json()["member"] is None, "other sessions are revoked"
    assert c.post("/api/auth/password/reset", json={"resetToken": token, "newPassword": "another-one-77"}, headers=h).status_code == 400
    notice = box.wait_for("zoe@example.com", count=3)
    assert notice.subject == "Your Hive password was reset"
    print("ok reset: weak password 422 (token survives), success logs in, revokes other sessions, token one-time, notice mailed")

    assert c.post("/api/auth/login", json={"username": "zoe", "password": "lime-tree-41"}, headers=h).status_code == 401
    assert c.post("/api/auth/login", json={"username": "zoe", "password": "new-dawn-2026"}, headers=h).status_code == 200
    print("ok old password rejected, new one works")

    # expired reset token
    c.post("/api/auth/password/forgot", json={"email": "kai@example.com"}, headers=h)
    kcode = box.code_for("kai@example.com", count=4)
    ktoken = c.post("/api/auth/password/verify", json={"email": "kai@example.com", "code": kcode}, headers=h).json()["resetToken"]

    async def expire(s):
        await s.execute(update(OtpChallenge).where(OtpChallenge.email == "kai@example.com").values(reset_expires_at=shift_iso(now(), -1)))
    db(expire)
    r = c.post("/api/auth/password/reset", json={"resetToken": ktoken, "newPassword": "brand-new-kai-1"}, headers=h)
    assert r.status_code == 400 and "expired" in r.json()["detail"]
    print("ok expired reset token -> 400")


def lockout_checks(c, box):
    h = fresh_ip()
    c.post("/api/auth/logout")
    for i in range(4):
        r = c.post("/api/auth/login", json={"username": "kai", "password": f"nope-{i}"}, headers=h)
        assert r.status_code == 401
    assert member("kai").failed_logins == 4, "failures persist despite the 401s"
    r = c.post("/api/auth/login", json={"username": "kai", "password": "nope-5"}, headers=h)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) == 15 * 60
    r = c.post("/api/auth/login", json={"username": "kai", "password": "harbor-lights-9"}, headers=h)
    assert r.status_code == 429, "right password refused while locked"
    assert member("kai").locked_until
    print("ok lockout: 5 wrong passwords lock the account; even the right password is refused")

    # a password reset lifts the lock
    c.post("/api/auth/password/forgot", json={"email": "kai@example.com"}, headers=h)
    code = box.code_for("kai@example.com", count=5)
    token = c.post("/api/auth/password/verify", json={"email": "kai@example.com", "code": code}, headers=h).json()["resetToken"]
    assert c.post("/api/auth/password/reset", json={"resetToken": token, "newPassword": "tidal-wave-31"}, headers=h).status_code == 200
    assert member("kai").locked_until is None and member("kai").failed_logins == 0
    c.post("/api/auth/logout")
    assert c.post("/api/auth/login", json={"username": "kai", "password": "tidal-wave-31"}, headers=h).status_code == 200
    print("ok password reset unlocks a locked account")

    # unknown usernames: same 401, no lockout bookkeeping to probe
    for _ in range(6):
        assert c.post("/api/auth/login", json={"username": "nobody", "password": "whatever-1"}, headers=h).status_code == 401
    print("ok unknown username -> plain 401 every time")


def session_checks(c, box):
    h = fresh_ip()
    from fastapi.testclient import TestClient
    from app.main import app
    other = TestClient(app)
    c.post("/api/auth/login", json={"username": "kai", "password": "tidal-wave-31"}, headers=h)
    other.post("/api/auth/login", json={"username": "kai", "password": "tidal-wave-31"}, headers=h)

    r = c.post("/api/account/password", json={"currentPassword": "tidal-wave-31", "newPassword": "kai"}, headers=h)
    assert r.status_code == 422
    r = c.post("/api/account/password", json={"currentPassword": "tidal-wave-31", "newPassword": "summit-air-88"}, headers=h)
    assert r.status_code == 200
    assert c.get("/api/auth/me").json()["member"]["username"] == "kai", "this device stays in"
    assert other.get("/api/auth/me").json()["member"] is None, "other devices are signed out"
    assert box.wait_for("kai@example.com", count=7).subject == "Your Hive password was changed"  # #6 = the reset notice
    print("ok password change: policy enforced, keeps this session, revokes others, notice mailed")

    other.post("/api/auth/login", json={"username": "kai", "password": "summit-air-88"}, headers=h)
    assert c.post("/api/auth/logout-all", headers=h).status_code == 200
    assert c.get("/api/auth/me").json()["member"] is None
    assert other.get("/api/auth/me").json()["member"] is None
    assert c.post("/api/auth/logout-all").status_code == 401
    print("ok log out everywhere revokes every session")

    # Cookies minted before session versioning (no `sv`) keep working until a bump.
    zoe = member("zoe")
    async def reset_version(s):
        await s.execute(update(Member).where(Member.id == zoe.id).values(session_version=0))
    db(reset_version)
    legacy = TimestampSigner("testsecret").sign(base64.b64encode(json.dumps({"member_id": zoe.id}).encode())).decode()
    fresh = TestClient(app)
    fresh.cookies.set("hive_session", legacy)
    assert fresh.get("/api/auth/me").json()["member"]["username"] == "zoe"
    forged = TimestampSigner("testsecret").sign(base64.b64encode(json.dumps({"member_id": zoe.id, "sv": "x"}).encode())).decode()
    bad = TestClient(app)
    bad.cookies.set("hive_session", forged)
    assert bad.get("/api/auth/me").json()["member"] is None
    print("ok legacy cookies (no session version) still authenticate; malformed version doesn't")


def email_change_checks(c, box):
    h = fresh_ip()
    c.post("/api/auth/login", json={"username": "zoe", "password": "new-dawn-2026"}, headers=h)
    r = c.post("/api/account/email", json={"email": "zoe.new@example.com"}, headers=h)
    assert r.status_code == 200
    j = r.json()
    assert j["email"] == "zoe@example.com" and j["pending"]["email"] == "zoe.new@example.com"
    assert c.get("/api/auth/me").json()["member"]["email"] == "zoe@example.com", "unchanged until verified"
    code = box.code_for("zoe.new@example.com")

    # another member can't redeem zoe's pending change
    other_h = fresh_ip()
    from fastapi.testclient import TestClient
    from app.main import app
    kai = TestClient(app)
    kai.post("/api/auth/login", json={"username": "kai", "password": "summit-air-88"}, headers=other_h)
    assert kai.post("/api/account/email/verify", json={"email": "zoe.new@example.com", "code": code}, headers=other_h).status_code == 400
    assert kai.post("/api/account/email", json={"email": "ZOE@example.com"}, headers=other_h).status_code == 409
    print("ok email change is member-scoped; another member's address -> 409")

    r = c.post("/api/account/email/verify", json={"email": "zoe.new@example.com", "code": code}, headers=h)
    assert r.status_code == 200 and r.json()["email"] == "zoe.new@example.com" and r.json()["emailVerified"] is True
    me = c.get("/api/auth/me").json()["member"]
    assert me["email"] == "zoe.new@example.com" and me["emailVerified"] is True
    print("ok verified code swaps the email in (verified)")

    r = c.post("/api/account/email", json={"email": "zoe.new@example.com"}, headers=h)
    assert r.json()["pending"] is None and box.count_to("zoe.new@example.com") == 1
    r = c.post("/api/account/email", json={"email": ""}, headers=h)
    assert r.json() == {"ok": True, "email": None, "emailVerified": False, "pending": None}
    print("ok same verified email is a no-op; clearing applies immediately")

    # A legacy (unverified) address can be verified in place, and still works for reset.
    async def legacy(s):
        m = await members_repo.get_by_username(s, "kai")
        m.email, m.email_verified_at = "Kai.Legacy@Example.com", None
    db(legacy)
    me = kai.get("/api/auth/me").json()["member"]
    assert me["emailVerified"] is False
    c.post("/api/auth/logout")
    assert c.post("/api/auth/password/forgot", json={"email": "kai.legacy@example.com"}, headers=h).status_code == 200
    code = box.code_for("kai.legacy@example.com")
    token = c.post("/api/auth/password/verify", json={"email": "kai.legacy@example.com", "code": code}, headers=h).json()["resetToken"]
    assert c.post("/api/auth/password/reset", json={"resetToken": token, "newPassword": "quiet-forest-5"}, headers=h).status_code == 200
    assert member("kai").email_verified_at is not None, "a completed reset proves the inbox"
    print("ok legacy unverified email: reset works (case-insensitive) and marks it verified")


def housekeeping_checks():
    async def plant(s):
        s.add(OtpChallenge(
            purpose="register", email="old@example.com", code_hash="x",
            created_at=shift_iso(now(), -90000), last_sent_at=shift_iso(now(), -90000),
            expires_at=shift_iso(now(), -89000),
        ))
    db(plant)
    assert challenge("old@example.com") is not None
    assert db(otp.purge) >= 1
    assert challenge("old@example.com") is None
    print("ok sweep purges challenges dead for over a day")


def rate_limit_checks(c):
    h = fresh_ip()
    ratelimit.login_limiter.reset()
    codes = [c.post("/api/auth/login", json={"username": "nobody", "password": "x-x-x-x-1"}, headers=h).status_code for _ in range(21)]
    assert codes[:20] == [401] * 20 and codes[20] == 429
    assert c.post("/api/auth/login", json={"username": "nobody", "password": "x-x-x-x-1"}, headers=fresh_ip()).status_code == 401
    print("ok per-IP throttle: 21st login attempt in the window -> 429 (other IPs unaffected)")


def main():
    unit_checks()
    asyncio.run(create_all())
    box = Mailbox.install()
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        signup_checks(c, box)
        expiry_attempts_resend_checks(c, box)
        forgot_password_checks(c, box)
        lockout_checks(c, box)
        session_checks(c, box)
        email_change_checks(c, box)
        housekeeping_checks()
        rate_limit_checks(c)

    print("\nAUTH/OTP SMOKE: ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
