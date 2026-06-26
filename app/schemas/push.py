"""Web Push contracts."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=1)
    auth: str = Field(min_length=1)


class PushSubscribeBody(BaseModel):
    endpoint: str = Field(min_length=1)
    keys: PushKeys


class PushUnsubscribeBody(BaseModel):
    endpoint: str = Field(min_length=1)
