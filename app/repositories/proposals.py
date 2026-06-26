"""Rule-proposal data access — proposals, votes, comments, events, anti-spam."""

from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import Row, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Member,
    ProposalComment,
    ProposalEvent,
    ProposalVote,
    RuleProposal,
)
from app.domain.enums import ProposalStatus
from app.repositories import fits_i64


# --- Proposal --------------------------------------------------------------

async def get(session: AsyncSession, proposal_id) -> Optional[RuleProposal]:
    if not fits_i64(proposal_id):
        return None
    return await session.get(RuleProposal, proposal_id)


async def insert(session: AsyncSession, **fields) -> RuleProposal:
    proposal = RuleProposal(**fields)
    session.add(proposal)
    await session.flush()
    return proposal


async def list_proposals(
    session: AsyncSession, status: Optional[str] = None, limit: int = 50
) -> list[RuleProposal]:
    stmt = select(RuleProposal)
    if status is not None:
        stmt = stmt.where(RuleProposal.status == status)
    stmt = stmt.order_by(RuleProposal.created_at.desc()).limit(limit)
    return list(await session.scalars(stmt))


async def due_ids(session: AsyncSession, now_iso_str: str) -> list[int]:
    """Voting proposals whose window has closed and aren't frozen."""
    return list(
        await session.scalars(
            select(RuleProposal.id).where(
                RuleProposal.status == ProposalStatus.VOTING,
                RuleProposal.frozen.is_(False),
                RuleProposal.voting_closes_at.is_not(None),
                RuleProposal.voting_closes_at < now_iso_str,
            )
        )
    )


# --- Votes -----------------------------------------------------------------

async def get_vote(
    session: AsyncSession, proposal_id: int, voter_id: int
) -> Optional[ProposalVote]:
    return await session.scalar(
        select(ProposalVote).where(
            ProposalVote.proposal_id == proposal_id, ProposalVote.voter_id == voter_id
        )
    )


async def record_vote(
    session: AsyncSession, proposal_id: int, voter_id: int, choice: str
) -> None:
    """Cast or change a vote (one per voter; latest wins while voting is open)."""
    existing = await get_vote(session, proposal_id, voter_id)
    if existing is None:
        session.add(ProposalVote(proposal_id=proposal_id, voter_id=voter_id, choice=choice))
    else:
        existing.choice = choice
    await session.flush()


async def vote_tally(session: AsyncSession, proposal_id: int) -> dict:
    stmt = select(
        func.coalesce(func.sum(case((ProposalVote.choice == "yes", 1), else_=0)), 0).label("yes"),
        func.coalesce(func.sum(case((ProposalVote.choice == "no", 1), else_=0)), 0).label("no"),
        func.coalesce(func.sum(case((ProposalVote.choice == "abstain", 1), else_=0)), 0).label("abstain"),
        func.count().label("total"),
    ).where(ProposalVote.proposal_id == proposal_id)
    row = (await session.execute(stmt)).one()
    return {"yes": row.yes, "no": row.no, "abstain": row.abstain, "total": row.total}


async def list_votes(session: AsyncSession, proposal_id: int) -> Sequence[Row]:
    stmt = (
        select(ProposalVote.choice, ProposalVote.ts, Member.name.label("voter_name"))
        .join(Member, Member.id == ProposalVote.voter_id)
        .where(ProposalVote.proposal_id == proposal_id)
        .order_by(ProposalVote.ts)
    )
    return (await session.execute(stmt)).all()


# --- Events ----------------------------------------------------------------

async def log_event(
    session: AsyncSession,
    *,
    proposal_id: int,
    type: str,
    actor_id: Optional[int] = None,
    detail: Optional[str] = None,
) -> ProposalEvent:
    event = ProposalEvent(proposal_id=proposal_id, type=type, actor_id=actor_id, detail=detail)
    session.add(event)
    await session.flush()
    return event


async def list_events(session: AsyncSession, proposal_id: int) -> Sequence[Row]:
    stmt = (
        select(ProposalEvent.type, ProposalEvent.detail, ProposalEvent.ts, Member.name.label("actor_name"))
        .outerjoin(Member, Member.id == ProposalEvent.actor_id)
        .where(ProposalEvent.proposal_id == proposal_id)
        .order_by(ProposalEvent.ts, ProposalEvent.id)
    )
    return (await session.execute(stmt)).all()


# --- Comments --------------------------------------------------------------

async def add_comment(
    session: AsyncSession,
    *,
    proposal_id: int,
    author_id: int,
    body: str,
    parent_id: Optional[int] = None,
) -> ProposalComment:
    comment = ProposalComment(
        proposal_id=proposal_id, author_id=author_id, body=body, parent_id=parent_id
    )
    session.add(comment)
    await session.flush()
    return comment


async def get_comment(session: AsyncSession, comment_id) -> Optional[ProposalComment]:
    if not fits_i64(comment_id):
        return None
    return await session.get(ProposalComment, comment_id)


async def list_comments(session: AsyncSession, proposal_id: int) -> Sequence[Row]:
    stmt = (
        select(
            ProposalComment.id,
            ProposalComment.parent_id,
            ProposalComment.body,
            ProposalComment.edited_at,
            ProposalComment.deleted,
            ProposalComment.created_at,
            ProposalComment.author_id,
            Member.name.label("author_name"),
        )
        .join(Member, Member.id == ProposalComment.author_id)
        .where(ProposalComment.proposal_id == proposal_id)
        .order_by(ProposalComment.created_at, ProposalComment.id)
    )
    return (await session.execute(stmt)).all()


# --- Anti-spam -------------------------------------------------------------

async def count_since(session: AsyncSession, proposer_id: int, since_iso: str) -> int:
    return await session.scalar(
        select(func.count())
        .select_from(RuleProposal)
        .where(RuleProposal.proposer_id == proposer_id, RuleProposal.created_at >= since_iso)
    )


async def find_recent_duplicate(
    session: AsyncSession, *, type: str, proposed_text: Optional[str], since_iso: str
) -> Optional[RuleProposal]:
    """A live proposal of the same type + same proposed text within the window."""
    if not proposed_text:
        return None
    return await session.scalar(
        select(RuleProposal)
        .where(
            RuleProposal.type == type,
            func.lower(RuleProposal.proposed_text) == func.lower(proposed_text),
            RuleProposal.created_at >= since_iso,
            RuleProposal.status.in_(
                (ProposalStatus.DRAFT, ProposalStatus.PENDING_REVIEW, ProposalStatus.VOTING, ProposalStatus.PASSED)
            ),
        )
        .order_by(RuleProposal.created_at.desc())
        .limit(1)
    )
