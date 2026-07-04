"""Push / device registration contracts (provider-agnostic; Web Push back-compatible)."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=1)
    auth: str = Field(min_length=1)


class PushSubscribeBody(BaseModel):
    """Register a push target. Back-compatible: the old Web-Push body `{endpoint, keys}`
    still works (provider defaults to 'webpush'). Native apps send
    `{provider:'fcm', platform:'android'|'ios', token}`."""

    provider: str = "webpush"           # webpush | fcm | apns
    platform: str = "web"               # web | android | ios
    token: Optional[str] = None         # FCM/APNS token, or the Web Push endpoint
    endpoint: Optional[str] = None      # legacy Web Push field (alias for token)
    keys: Optional[PushKeys] = None     # Web Push only


class PushUnsubscribeBody(BaseModel):
    # `endpoint` doubles as the token for native providers.
    endpoint: str = Field(min_length=1)
