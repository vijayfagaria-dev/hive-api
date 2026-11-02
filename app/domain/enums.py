"""Domain vocabulary — statuses, transitions, and the values shared across layers.

A complaint *is* a fine. The persisted
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


class PaymentStatus(StrEnum):
    """The fine's PAYMENT lifecycle — a second, explicit axis kept separate from the
    complaint-resolution `status` (Bug 2). Acceptance/registration only creates the
    obligation (OWED); it never settles. Replaces the old lone `paid` boolean.

        NOT_OWED ──register──► OWED ──pay_by elapses──► OVERDUE
                                 │                         │
                                 └──── mark paid ──────────┘
                                          ▼
                                    MARKED_PAID ──verify──► SETTLED
                                          └──(verification off)──► SETTLED
    """

    NOT_OWED = "not_owed"        # complaint not registered as a debt (pending / void)
    OWED = "owed"                # registered; payment pending, countdown running
    OVERDUE = "overdue"          # pay_by elapsed, still unpaid
    MARKED_PAID = "marked_paid"  # payer self-attested; awaiting optional verification
    SETTLED = "settled"          # done


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
    PAYMENT_DUE = "payment_due"    # obligation registered; pay-by countdown started
    OVERDUE = "overdue"            # pay-by elapsed, still unpaid
    PAID = "paid"                  # payer marked it paid
    SETTLED = "settled"            # verified paid (when verification is enabled)


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


# --- Expenses (the unified Splitwise-style money model) ---------------------

class ExpenseCategory(StrEnum):
    RENT = "rent"                 # fronted by one tenant, split by rent-share % (see services/rent.py)
    MAINTENANCE = "maintenance"   # water / electricity / gas / cleaner and other flat upkeep
    INTERNET = "internet"
    HOUSE_HELP = "house_help"
    COOK = "cook"
    GROCERIES = "groceries"
    BROKER = "broker"
    MISC = "misc"


class SplitStrategy(StrEnum):
    EQUAL = "equal"            # split evenly across participants
    RATIO = "ratio"           # by per-participant weights (e.g. 27/27/27/19)
    PERCENTAGE = "percentage"  # by per-participant %, must total 100
    SHARES = "shares"         # by arbitrary integer shares (2:2:1)
    FIXED = "fixed"           # explicit rupees per participant, must sum to total
    CUSTOM = "custom"         # explicit rupees (distinct UX label), must sum to total


class ExpenseStatus(StrEnum):
    PENDING = "pending"        # declared; awaiting confirmation window / dispute
    CONFIRMED = "confirmed"
    DISPUTED = "disputed"
    VOID = "void"             # soft-deleted; excluded from every balance


class PaymentMethod(StrEnum):
    UPI = "upi"
    CASH = "cash"
    ADJUSTMENT = "adjustment"  # a manual balance correction, not a real transfer


class ExpenseEventType(StrEnum):
    CREATED = "created"
    EDITED = "edited"
    VOIDED = "voided"
    DISPUTED = "disputed"
    CONFIRMED = "confirmed"
    GENERATED = "generated"    # produced by the recurring sweep


class RecurrenceFreq(StrEnum):
    MONTHLY = "monthly"


class RecurringStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ENDED = "ended"


# --- Money ledger (rent shares, advances, broker, settlement, penalties) -----

class LedgerEntryType(StrEnum):
    ADVANCE = "advance"        # money a member pre-paid (credit)
    DEPOSIT = "deposit"        # security-deposit share (debit) / paid (credit)
    BROKER = "broker"          # one-time broker fee, split by rent ratio
    PENALTY = "penalty"        # unpaid-fine penalty: debit the defaulter, credit the others
    PAYOUT = "payout"          # fine-pot leftover returned at a settlement
    ADJUSTMENT = "adjustment"  # manual admin correction

# Amount sign convention on ledger_entries: a POSITIVE amount is a credit (the flat owes
# the member / they're ahead); a NEGATIVE amount is a debit (the member owes the flat).


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

# Payment states in which a registered fine can still be paid (an obligation exists).
PAYABLE_STATUSES: tuple[str, ...] = (PaymentStatus.OWED, PaymentStatus.OVERDUE)

# Statuses that count as a *decided rejection* of a complaint — i.e. the reporter
# was overturned. Only VOID is terminal-rejected; DISPUTED is an in-flight vote and
# must NOT count (it isn't a rejection yet). Mirrors OWED_STATUSES so aggregation
# predicates never drift back into inline string literals.
REJECTED_STATUSES: tuple[str, ...] = (FineStatus.VOID,)

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
    # Money surface (previously gated only at the route with require_tenant; now also
    # enforced in the services for defense-in-depth). Tenants hold all of these.
    CREATE_EXPENSE = "create_expense"
    EDIT_EXPENSE = "edit_expense"
    SETTLE = "settle"              # record payments / close a settle-up run
    # Read the flat-wide money picture (everyone's expenses, balances, rent, settle-up,
    # ledger). Tenants only — a guest sees just their own statement and their fines.
    VIEW_FINANCES = "view_finances"


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


# --- Auth: one-time email codes ---------------------------------------------

class OtpPurpose(StrEnum):
    REGISTER = "register"              # verify the email before the account exists
    PASSWORD_RESET = "password_reset"  # prove the inbox to set a new password
    CHANGE_EMAIL = "change_email"      # confirm a new address before it replaces the old
