"""Test helper — capture transactional mail and complete an email-verified signup.

    from mailbox import Mailbox, signup
    box = Mailbox.install()          # before the app sends anything
    member = signup(c, box, "zoe", "zoe-pass-123")
"""

from __future__ import annotations

import re
import time

from app.infra import mailer

_CODE = re.compile(r"\b(\d{3}) (\d{3})\b")


class Mailbox:
    def __init__(self) -> None:
        self.sent: list[mailer.Message] = []

    @classmethod
    def install(cls) -> "Mailbox":
        box = cls()
        mailer.transport = box.sent.append
        return box

    def wait_for(self, to: str, *, count: int = 1, timeout: float = 3.0) -> mailer.Message:
        """The `count`-th message to `to` (mail goes out on a post-commit task)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            mine = [m for m in self.sent if m.to == to]
            if len(mine) >= count:
                return mine[count - 1]
            time.sleep(0.02)
        raise AssertionError(f"no email #{count} to {to} (got {[m.to for m in self.sent]})")

    def count_to(self, to: str, settle: float = 0.3) -> int:
        time.sleep(settle)
        return sum(1 for m in self.sent if m.to == to)

    def code_for(self, to: str, *, count: int = 1) -> str:
        msg = self.wait_for(to, count=count)
        match = _CODE.search(msg.text)
        assert match, f"no code in email to {to}"
        return match.group(1) + match.group(2)


def signup(c, box: Mailbox, username: str, password: str, *, email: str | None = None, invite: str | None = None, **extra):
    """Register through the OTP flow; returns the verify response (status checked)."""
    email = email or f"{username.lower()}@example.com"
    r = c.post(
        "/api/auth/register",
        json={"username": username, "password": password, "email": email, "invite": invite, **extra},
    )
    assert r.status_code == 200, r.text
    n = sum(1 for m in box.sent if m.to == email) or 1
    code = box.code_for(email, count=n)
    return c.post("/api/auth/register/verify", json={"email": email, "code": code})
