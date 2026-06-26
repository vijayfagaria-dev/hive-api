"""ORM models. Importing this package registers every table on Base.metadata
(used by create_all and Alembic autogenerate)."""

from app.db.models.bill import Bill, BillShare
from app.db.models.fine import Fine, FineEvent, FineProof, FineVote
from app.db.models.member import Member
from app.db.models.notification import Notification
from app.db.models.proposal import (
    ProposalComment,
    ProposalEvent,
    ProposalVote,
    RuleProposal,
)
from app.db.models.push import PushSubscription
from app.db.models.rule import Rule
from app.db.models.rule_version import RuleVersion

__all__ = [
    "Member",
    "Rule",
    "RuleVersion",
    "Fine",
    "FineProof",
    "FineEvent",
    "FineVote",
    "Bill",
    "BillShare",
    "Notification",
    "PushSubscription",
    "RuleProposal",
    "ProposalVote",
    "ProposalComment",
    "ProposalEvent",
]
