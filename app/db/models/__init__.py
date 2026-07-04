"""ORM models. Importing this package registers every table on Base.metadata
(used by create_all and Alembic autogenerate)."""

from app.db.models.bill import Bill, BillEvent, BillShare
from app.db.models.expense import (
    Expense,
    ExpenseEvent,
    ExpenseSplit,
    ExpenseTemplate,
    Payment,
    RecurringExpense,
    SettleRun,
    SettleTxn,
)
from app.db.models.fine import Fine, FineEvent, FineProof, FineVote
from app.db.models.invitation import Invitation
from app.db.models.ledger import LedgerEntry, Settlement
from app.db.models.member import Member
from app.db.models.member_event import MemberEvent
from app.db.models.notification import Notification, NotificationOutbox
from app.db.models.proposal import (
    ProposalComment,
    ProposalEvent,
    ProposalVote,
    RuleProposal,
)
from app.db.models.push import Device, PushSubscription
from app.db.models.rule import Rule
from app.db.models.rule_version import RuleVersion

__all__ = [
    "Member",
    "MemberEvent",
    "Invitation",
    "Rule",
    "RuleVersion",
    "Fine",
    "FineProof",
    "FineEvent",
    "FineVote",
    "Bill",
    "BillShare",
    "BillEvent",
    "Expense",
    "ExpenseSplit",
    "Payment",
    "ExpenseEvent",
    "ExpenseTemplate",
    "RecurringExpense",
    "SettleRun",
    "SettleTxn",
    "LedgerEntry",
    "Settlement",
    "Notification",
    "NotificationOutbox",
    "PushSubscription",
    "Device",
    "RuleProposal",
    "ProposalVote",
    "ProposalComment",
    "ProposalEvent",
]
