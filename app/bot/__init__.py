"""The Telegram bot (aiogram 3) — the tap-driven input surface for Hive.

Flows are STATELESS: everything needed to continue a multi-step action is encoded
in the inline-button callback data (see callbacks.py), so there's no FSM to confuse
in a shared group chat. The only free-text inputs are command args (`/fine dishes`,
`/bill electricity 2400`).

Public entry points (used by app/main.py in Phase 4):
  create_bot()         -> Bot | None      (None when no token is configured)
  create_dispatcher(db) -> Dispatcher     (routers + member middleware + db DI)
"""

from .setup import create_bot, create_dispatcher

__all__ = ["create_bot", "create_dispatcher"]
