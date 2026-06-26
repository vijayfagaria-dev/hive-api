"""Rule-proposal routes — propose, vote, comment, timeline, and admin controls."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_login, require_tenant
from app.core.errors import NotFound
from app.repositories import proposals as proposals_repo
from app.repositories import members as members_repo
from app.schemas.proposals import (
    CommentBody,
    CommentEditBody,
    ExtendBody,
    FreezeBody,
    ProposalCreate,
    ProposalUpdate,
    ProposalVoteBody,
    comment_out,
    detail_out,
    event_out,
    proposal_out,
    vote_row_out,
)
from app.services import proposals

router = APIRouter(prefix="/proposals", tags=["proposals"])


# --- Create / read / edit --------------------------------------------------

@router.post("")
async def create_proposal(
    body: ProposalCreate, session: AsyncSession = Depends(get_session), member=Depends(require_login)
):
    proposal_id = await proposals.create(
        session, proposer_id=member.id, type=body.type, title=body.title, body=body.body,
        target_rule_id=body.targetRuleId, proposed_category=body.proposedCategory,
        proposed_text=body.proposedText, proposed_amount=body.proposedAmount, submit=body.submit,
    )
    return {"ok": True, "proposalId": proposal_id}


@router.get("")
async def list_proposals(
    status: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
    member=Depends(require_login),
):
    items = await proposals_repo.list_proposals(session, status)
    out = []
    for p in items:
        proposer = await members_repo.get(session, p.proposer_id)
        tally = await proposals_repo.vote_tally(session, p.id)
        out.append(proposal_out(p, proposer=proposer, tally=tally))
    return {"proposals": out}


@router.get("/{proposal_id}")
async def proposal_detail(
    proposal_id: int, session: AsyncSession = Depends(get_session), member=Depends(require_login)
):
    return detail_out(await proposals.get_detail(session, proposal_id, member))


@router.patch("/{proposal_id}")
async def update_proposal(
    proposal_id: int, body: ProposalUpdate,
    session: AsyncSession = Depends(get_session), member=Depends(require_login),
):
    proposal = await proposals_repo.get(session, proposal_id)
    if proposal is None:
        raise NotFound("No such proposal.")
    await proposals.update(
        session, proposal, member, expected_version=body.expectedVersion,
        title=body.title, body=body.body, proposed_category=body.proposedCategory,
        proposed_text=body.proposedText, proposed_amount=body.proposedAmount,
    )
    return {"ok": True}


@router.post("/{proposal_id}/submit")
async def submit_proposal(
    proposal_id: int, session: AsyncSession = Depends(get_session), member=Depends(require_login)
):
    proposal = await proposals_repo.get(session, proposal_id)
    if proposal is None:
        raise NotFound("No such proposal.")
    status = await proposals.submit_proposal(session, proposal, by_member=member)
    return {"ok": True, "status": status}


# --- Voting ----------------------------------------------------------------

@router.post("/{proposal_id}/vote")
async def vote(
    proposal_id: int, body: ProposalVoteBody,
    session: AsyncSession = Depends(get_session), member=Depends(require_login),
):
    tally = await proposals.vote(session, proposal_id, member.id, body.vote)
    return {"ok": True, "tally": {"yes": tally["yes"], "no": tally["no"], "abstain": tally["abstain"]}}


@router.get("/{proposal_id}/votes")
async def proposal_votes(
    proposal_id: int, session: AsyncSession = Depends(get_session), member=Depends(require_login)
):
    return {
        "tally": await proposals_repo.vote_tally(session, proposal_id),
        "votes": [vote_row_out(v) for v in await proposals_repo.list_votes(session, proposal_id)],
    }


@router.get("/{proposal_id}/timeline")
async def proposal_timeline(
    proposal_id: int, session: AsyncSession = Depends(get_session), member=Depends(require_login)
):
    return {"timeline": [event_out(e) for e in await proposals_repo.list_events(session, proposal_id)]}


# --- Comments --------------------------------------------------------------

@router.get("/{proposal_id}/comments")
async def list_comments(
    proposal_id: int, session: AsyncSession = Depends(get_session), member=Depends(require_login)
):
    return {"comments": [comment_out(c) for c in await proposals_repo.list_comments(session, proposal_id)]}


@router.post("/{proposal_id}/comments")
async def add_comment(
    proposal_id: int, body: CommentBody,
    session: AsyncSession = Depends(get_session), member=Depends(require_login),
):
    comment_id = await proposals.add_comment(session, proposal_id, member, body.body, body.parentId)
    return {"ok": True, "commentId": comment_id}


@router.patch("/{proposal_id}/comments/{comment_id}")
async def edit_comment(
    proposal_id: int, comment_id: int, body: CommentEditBody,
    session: AsyncSession = Depends(get_session), member=Depends(require_login),
):
    await proposals.edit_comment(session, comment_id, member, body.body)
    return {"ok": True}


@router.delete("/{proposal_id}/comments/{comment_id}")
async def delete_comment(
    proposal_id: int, comment_id: int,
    session: AsyncSession = Depends(get_session), member=Depends(require_login),
):
    await proposals.delete_comment(session, comment_id, member)
    return {"ok": True}


# --- Cancel (proposer or admin) --------------------------------------------

@router.post("/{proposal_id}/cancel")
async def cancel_proposal(
    proposal_id: int, session: AsyncSession = Depends(get_session), member=Depends(require_login)
):
    status = await proposals.cancel(session, proposal_id, member)
    return {"ok": True, "status": status}


# --- Admin (tenant) controls -----------------------------------------------

@router.post("/{proposal_id}/approve")
async def approve(
    proposal_id: int, session: AsyncSession = Depends(get_session), member=Depends(require_tenant)
):
    return {"ok": True, "status": await proposals.approve(session, proposal_id, member)}


@router.post("/{proposal_id}/reject")
async def reject(
    proposal_id: int, session: AsyncSession = Depends(get_session), member=Depends(require_tenant)
):
    return {"ok": True, "status": await proposals.reject(session, proposal_id, member)}


@router.post("/{proposal_id}/extend")
async def extend(
    proposal_id: int, body: ExtendBody,
    session: AsyncSession = Depends(get_session), member=Depends(require_tenant),
):
    await proposals.extend(session, proposal_id, member, body.hours)
    return {"ok": True}


@router.post("/{proposal_id}/freeze")
async def freeze(
    proposal_id: int, body: FreezeBody,
    session: AsyncSession = Depends(get_session), member=Depends(require_tenant),
):
    await proposals.freeze(session, proposal_id, member, body.frozen)
    return {"ok": True}


@router.post("/{proposal_id}/force-merge")
async def force_merge(
    proposal_id: int, session: AsyncSession = Depends(get_session), member=Depends(require_tenant)
):
    return {"ok": True, "status": await proposals.force_merge(session, proposal_id, member)}
