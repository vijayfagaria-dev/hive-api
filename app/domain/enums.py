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


# --- Bills (declare-and-confirm lifecycle) ----------------------------------

class BillStatus(StrEnum):
    PENDING = "pending"      # the payer declared "I paid"; awaiting the 12h sweep or a dispute
    CONFIRMED = "confirmed"  # nobody disputed in time -> settled
    DISPUTED = "disputed"    # a tenant disputed before the deadline; never auto-confirms


class BillEventType(StrEnum):
    CREATED = "created"                # the payer declared the bill
    AUTO_CONFIRMED = "auto_confirmed"  # confirmation window elapsed, undisputed
    DISPUTED = "disputed"
    RESOLVED = "resolved"              # reserved: future dispute resolution / voting


# --- Rule proposals ---------------------------------------------------------

class ProposalStatus(StrEnum):
    DRAFT = "draft"                  # being written by the proposer
    PENDING_REVIEW = "pending_review"  # awaiting admin approval (if review is on)
    VOTING = "voting"               # open for votes until voting_closes_at
    PASSED = "passed"               # met the passing conditions; merged into the rule book
    REJECTED = "rejected"           # failed the passing conditions
    EXPIRED = "expired"             # voting closed with no quorum
    CANCELLED = "cancelled"         # withdrawn by proposer / killed by admin


class ProposalType(StrEnum):
    NEW_RULE = "new_rule"
    MODIFY_RULE = "modify_rule"
    DELETE_RULE = "delete_rule"


class ProposalVoteChoice(StrEnum):
    YES = "yes"
    NO = "no"
    ABSTAIN = "abstain"  # counts toward quorum, not toward the yes/no ratio


class ProposalEventType(StrEnum):
    CREATED = "created"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    VOTING_OPENED = "voting_opened"
    VOTE_CAST = "vote_cast"
    COMMENTED = "commented"
    EXTENDED = "extended"
    FROZEN = "frozen"
    VOTING_CLOSED = "voting_closed"
    PASSED = "passed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    MERGED = "merged"


# Persisted proposal status -> the phase the frontend renders.
PROPOSAL_PHASE: dict[str, str] = {
    ProposalStatus.DRAFT: "draft",
    ProposalStatus.PENDING_REVIEW: "review",
    ProposalStatus.VOTING: "voting",
    ProposalStatus.PASSED: "passed",
    ProposalStatus.REJECTED: "rejected",
    ProposalStatus.EXPIRED: "rejected",
    ProposalStatus.CANCELLED: "cancelled",
}


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


# --- Household user management ----------------------------------------------

class Permission(StrEnum):
    """Granular capabilities. Authorization checks reference a Permission, never a
    role literal, so new roles (Owner, Moderator, Read-only, House Manager…) slot
    in by editing the role→permission policy alone (app/domain/permissions.py)."""

    VIEW_MEMBERS = "view_members"
    INVITE_MEMBER = "invite_member"
    UPDATE_ROLE = "update_role"
    REMOVE_MEMBER = "remove_member"
    MANAGE_USERS = "manage_users"  # umbrella; also marks a role as "admin"


class MemberEventType(StrEnum):
    """Append-only audit trail for household-management actions on a member."""

    JOINED = "joined"                    # self-registration
    INVITE_ACCEPTED = "invite_accepted"  # joined by redeeming an invite
    ROLE_CHANGED = "role_changed"
    RENAMED = "renamed"
    REMOVED = "removed"
    REACTIVATED = "reactivated"


class InvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"
    EXPIRED = "expired"
