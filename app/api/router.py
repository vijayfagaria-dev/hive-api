"""The single /api router — composes every per-resource route module.

Adding a resource = add a route module and include it here; nothing else changes.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import (
    account,
    auth,
    bills,
    complaints,
    home,
    household,
    notifications,
    payments,
    proposals,
    rulebook,
)

api_router = APIRouter(prefix="/api")

api_router.include_router(auth.router)
api_router.include_router(home.router)
api_router.include_router(complaints.router)
api_router.include_router(complaints.proofs_router)
api_router.include_router(bills.router)
api_router.include_router(payments.router)
api_router.include_router(notifications.router)
api_router.include_router(account.router)
api_router.include_router(proposals.router)
api_router.include_router(rulebook.router)
api_router.include_router(household.router)
