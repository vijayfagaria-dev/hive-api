"""Per-client throttling for the public auth endpoints.

An in-process sliding window — fine for this app's single uvicorn worker (see
deploy/hive-api.service). It is the coarse outer guard; the durable, per-account
limits (login lockout, OTP attempts/cooldowns) live in the database.

Client IP: the browser reaches us through Caddy -> Next.js -> uvicorn, so the TCP
peer is always loopback. When it is, the left-most X-Forwarded-For entry is the
real client (Caddy overwrites any client-supplied value with the true peer).
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from ipaddress import ip_address

from starlette.requests import Request

from app.core.config import settings
from app.core.errors import TooManyRequests


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else ""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded and _is_internal(peer):
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return peer or "unknown"


def _is_internal(host: str) -> bool:
    try:
        addr = ip_address(host)
    except ValueError:
        return host in ("testclient", "localhost")
    return addr.is_loopback or addr.is_private


class RateLimiter:
    """At most `limit` hits per `window` seconds for each key."""

    def __init__(self, name: str, limit: int, window: int) -> None:
        self.name = name
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str) -> None:
        if not settings.rate_limit_enabled:
            return
        now = time.monotonic()
        hits = self._hits[key]
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            retry = int(hits[0] + self.window - now) + 1
            raise TooManyRequests("Too many attempts — slow down and try again shortly.", retry_after=retry)
        hits.append(now)
        if len(self._hits) > 10_000:  # bound memory under a spray of distinct IPs
            self._prune(now)

    def _prune(self, now: float) -> None:
        for key in [k for k, v in self._hits.items() if not v or v[-1] <= now - self.window]:
            del self._hits[key]

    def reset(self) -> None:
        self._hits.clear()

    def dependency(self):
        """FastAPI dependency: throttle the route by client IP."""

        async def _dep(request: Request) -> None:
            self.hit(client_ip(request))

        return _dep


login_limiter = RateLimiter("login", limit=20, window=5 * 60)
register_limiter = RateLimiter("register", limit=10, window=60 * 60)
otp_request_limiter = RateLimiter("otp-request", limit=10, window=15 * 60)
otp_verify_limiter = RateLimiter("otp-verify", limit=30, window=15 * 60)
