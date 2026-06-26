"""Domain vocabulary — statuses, transitions, and the values shared across layers.

A complaint *is* a fine (DESIGN.md "Handling fine-system abuse"). The persisted
status enum is intentionally small; the "voting" phase is status='disputed' with
an open vote_deadline. Keeping these as one source prevents magic strings drifting
across the API, services, and repositories.
"""

from __future__ import annotations

from enum import StrEnum


class FineStatus(StrEnum):
    PENDING = "pending"      # raised; awaiting accept/deny or the cooling sweep
    CONFIRMED = "confirmed"  # registered via accept / auto-confirm
    DISPUTED = "disputed"    # denied -> a member vote is open ("voting" phase)
    UPHELD = "upheld"        # registered by majority vote
    VOID = "void"            # rejected by vote / tie / no quorum


class Resolution(StrEnum):
    ACCEPTED = "accepted"
    AUTO_CONFIRMED = "auto_confirmed"
    UPHELD = "upheld"
    VOID = "void"


class Vote(StrEnum):
    UPHOLD = "uphold"
    VOID = "void"


class ProofSource(StrEnum):
    UPLOAD = "upload"
    TELEGRAM = "telegram"  # legacy (bot retired); kept for old rows


class Role(StrEnum):
    TENANT = "tenant"
    GUEST = "guest"


class EventType(StrEnum):
    RAISED = "raised"
    ACCUSED_NOTIFIED = "accused_notified"
    ACCEPTED = "accepted"
    DISPUTED = "disputed"
    VOTING_STARTED = "voting_started"
    MEMBERS_NOTIFIED = "members_notified"
    VOTE_CAST = "vote_cast"
    VOTE_FINALIZED = "vote_finalized"
    AUTO_CONFIRMED = "auto_confirmed"
    PAID = "paid"


# Statuses that count as money owed / in the pot.
OWED_STATUSES: tuple[str, ...] = (FineStatus.CONFIRMED, FineStatus.UPHELD)

# The only four bills this app splits (closed by design).
BILL_TYPES: tuple[str, ...] = ("rent", "house_help", "electricity", "water")

# Persisted status -> the workflow phase the frontend renders.
PHASE: dict[str, str] = {
    FineStatus.PENDING: "raised",
    FineStatus.CONFIRMED: "registered",
    FineStatus.DISPUTED: "voting",
    FineStatus.UPHELD: "registered",
    FineStatus.VOID: "rejected",
}
