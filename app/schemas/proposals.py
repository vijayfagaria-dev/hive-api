"""Rule-proposal contracts — request bodies + response mappers."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.domain.enums import PROPOSAL_PHASE
from app.schemas.accounts import member_out


class ProposalCreate(BaseModel):
    type: str  # new_rule | modify_rule | delete_rule
    title: str = Field(min_length=1, max_length=140)
    body: Optional[str] = Field(default=None, max_length=5000)
    targetRuleId: Optional[int] = None
    proposedCategory: Optional[str] = Field(default=None, max_length=64)
    proposedText: Optional[str] = Field(default=None, max_length=500)
    proposedAmount: Optional[int] = None
    submit: bool = True


class ProposalUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=140)
    body: Optional[str] = Field(default=None, max_length=5000)
    proposedCategory: Optional[str] = Field(default=None, max_length=64)
    proposedText: Optional[str] = Field(default=None, max_length=500)
    proposedAmount: Optional[int] = None
    expectedVersion: Optional[int] = None  # optimistic lock


class ProposalVoteBody(BaseModel):
    vote: str  # yes | no | abstain


class CommentBody(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    parentId: Optional[int] = None


class CommentEditBody(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class ExtendBody(BaseModel):
    hours: int = Field(gt=0, le=720)


class FreezeBody(BaseModel):
    frozen: bool = True


def proposal_out(proposal, proposer=None, tally: Optional[dict] = None) -> dict:
    out = {
        "id": proposal.id,
        "type": proposal.type,
        "status": proposal.status,
        "phase": PROPOSAL_PHASE.get(proposal.status, proposal.status),
        "title": proposal.title,
        "targetRuleId": proposal.target_rule_id,
        "proposedCategory": proposal.proposed_category,
        "proposedText": proposal.proposed_text,
        "proposedAmount": proposal.proposed_amount,
        "votingOpensAt": proposal.voting_opens_at,
        "votingClosesAt": proposal.voting_closes_at,
        "resolvedAt": proposal.resolved_at,
        "resolutionDetail": proposal.resolution_detail,
        "mergedRuleId": proposal.merged_rule_id,
        "frozen": bool(proposal.frozen),
        "createdAt": proposal.created_at,
        "version": proposal.version,
    }
    if proposer is not None:
        out["proposer"] = member_out(proposer)
    if tally is not None:
        out["tally"] = {"yes": tally["yes"], "no": tally["no"], "abstain": tally["abstain"]}
    return out


def comment_out(row) -> dict:
    return {
        "id": row.id,
        "author": row.author_name,
        "authorId": row.author_id,
        "parentId": row.parent_id,
        "body": None if row.deleted else row.body,
        "edited": row.edited_at is not None,
        "deleted": bool(row.deleted),
        "ts": row.created_at,
    }


def event_out(row) -> dict:
    return {"type": row.type, "actor": row.actor_name, "detail": row.detail, "ts": row.ts}


def vote_row_out(row) -> dict:
    return {"choice": row.choice, "voter": row.voter_name, "ts": row.ts}


def detail_out(detail: dict) -> dict:
    proposal = detail["proposal"]
    tally = detail["tally"]
    out = proposal_out(proposal, proposer=detail["proposer"])
    out.update(
        {
            "body": proposal.body,
            "vote": {
                "yes": tally["yes"],
                "no": tally["no"],
                "abstain": tally["abstain"],
                "eligible": detail["eligible"],
                "myVote": detail["my_vote"],
            },
            "comments": [comment_out(c) for c in detail["comments"]],
            "timeline": [event_out(e) for e in detail["events"]],
            "canVote": detail["can_vote"],
            "canEdit": detail["can_edit"],
            "canAdmin": detail["can_admin"],
        }
    )
    return out
