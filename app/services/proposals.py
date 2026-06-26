"""Rule-proposal lifecycle — the state machine lives here, nowhere else.

  draft ─submit─► pending_review ─approve─► voting ─(close)─► passed | rejected | expired
     │                  (if review off, submit opens voting directly)        │
     └──────────────────────── cancel (proposer/admin) ────────► cancelled   └─ passed ⇒ merged into rules
                                                                                  (+ immutable rule_versions)

Tenants vote (one each, changeable until the deadline). At close the configurable
passing conditions (quorum + majority% + min-yes) decide the outcome; a passed
proposal is auto-merged into the rule book. Every step appends a proposal_events
row and fans a notification out. Admin (tenant) actions: approve/reject/extend/
freeze/cancel/force-merge. Repositories do the I/O; this owns the policy.
"""

from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import Conflict, DomainError, Forbidden, NotFound, Unprocessable
from app.core.sanitize import clean
from app.domain.enums import (
    ProposalEventType,
    ProposalStatus,
    ProposalType,
    ProposalVoteChoice,
    Role,
)
from app.domain.time import deadline_iso, iso, now, now_iso
from app.repositories import members as members_repo
from app.repositories import proposals as proposals_repo
from app.repositories import rule_versions as rule_versions_repo
from app.repositories import rules as rules_repo
from app.services import notifications

_TYPES = {ProposalType.NEW_RULE, ProposalType.MODIFY_RULE, ProposalType.DELETE_RULE}


def _require_admin(member) -> None:
    if member is None or member.role != Role.TENANT:
        raise Forbidden("Admin (tenant) only.")


async def _eligible_voters(session: AsyncSession):
    """Tenants only vote on rule proposals (configured choice)."""
    return await members_repo.list_active_tenants(session)


# --- Create / submit -------------------------------------------------------

async def create(
    session: AsyncSession,
    *,
    proposer_id: int,
    type: str,
    title: str,
    body: Optional[str] = None,
    target_rule_id: Optional[int] = None,
    proposed_category: Optional[str] = None,
    proposed_text: Optional[str] = None,
    proposed_amount: Optional[int] = None,
    submit: bool = True,
) -> int:
    """Create a proposal (and, by default, submit it). Returns the new id."""
    if type not in _TYPES:
        raise Unprocessable(f"type must be one of {sorted(_TYPES)}.")
    proposer = await members_repo.get(session, proposer_id)
    if proposer is None or not proposer.is_active:
        raise DomainError("Only an active member can propose a rule.")
    title = (title or "").strip()
    if len(title) < 3:
        raise Unprocessable("Give the proposal a title (at least 3 characters).")

    body = clean(body)
    proposed_text = clean(proposed_text, max_len=500)
    if proposed_amount is not None and proposed_amount < 0:
        raise Unprocessable("A fine amount can't be negative.")

    target = None
    if type in (ProposalType.MODIFY_RULE, ProposalType.DELETE_RULE):
        target = await rules_repo.get(session, target_rule_id)
        if target is None:
            raise DomainError("That rule doesn't exist to modify/delete.")
    if type == ProposalType.NEW_RULE and not proposed_text:
        raise Unprocessable("A new-rule proposal needs the proposed rule text.")

    await _check_anti_spam(session, proposer_id=proposer_id, type=type, proposed_text=proposed_text)

    proposal = await proposals_repo.insert(
        session,
        proposer_id=proposer_id,
        type=type,
        status=ProposalStatus.DRAFT,
        target_rule_id=target.id if target else None,
        title=title,
        body=body,
        proposed_category=clean(proposed_category, max_len=64),
        proposed_text=proposed_text,
        proposed_amount=proposed_amount,
    )
    await proposals_repo.log_event(
        session, proposal_id=proposal.id, type=ProposalEventType.CREATED, actor_id=proposer_id
    )
    if submit:
        await submit_proposal(session, proposal, by_member=proposer)
    return proposal.id


async def _check_anti_spam(
    session: AsyncSession, *, proposer_id: int, type: str, proposed_text: Optional[str]
) -> None:
    if settings.proposal_max_per_day > 0:
        since = deadline_iso(now(), -24)
        if await proposals_repo.count_since(session, proposer_id, since) >= settings.proposal_max_per_day:
            raise DomainError(
                f"You've hit the limit of {settings.proposal_max_per_day} proposals in 24h."
            )
    since = deadline_iso(now(), -24)
    if await proposals_repo.find_recent_duplicate(
        session, type=type, proposed_text=proposed_text, since_iso=since
    ):
        raise DomainError("A near-identical proposal is already live — go vote on that one.")


async def submit_proposal(session: AsyncSession, proposal, by_member) -> str:
    """Draft -> pending_review (if review required) or straight to voting."""
    if proposal.status != ProposalStatus.DRAFT:
        return proposal.status
    if by_member.id != proposal.proposer_id and by_member.role != Role.TENANT:
        raise Forbidden("Only the proposer can submit this proposal.")
    if not proposal.body or len(proposal.body) < settings.proposal_min_body_len:
        raise Unprocessable(
            f"Add a rationale of at least {settings.proposal_min_body_len} characters before submitting."
        )

    await proposals_repo.log_event(
        session, proposal_id=proposal.id, type=ProposalEventType.SUBMITTED, actor_id=by_member.id
    )
    if settings.proposal_require_review:
        proposal.status = ProposalStatus.PENDING_REVIEW
        admins = await members_repo.list_active_tenants(session)
        await notifications.proposal_resolved(
            session, recipients=admins, proposal_id=proposal.id, kind="proposal_review",
            title="🧐 A rule proposal needs review",
            body=f"“{proposal.title}” is awaiting approval before voting opens.",
        )
        return proposal.status
    return await _open_voting(session, proposal)


async def _open_voting(session: AsyncSession, proposal) -> str:
    created = now()
    proposal.status = ProposalStatus.VOTING
    proposal.voting_opens_at = iso(created)
    proposal.voting_closes_at = deadline_iso(created, settings.proposal_voting_hours)
    await proposals_repo.log_event(
        session, proposal_id=proposal.id, type=ProposalEventType.VOTING_OPENED,
        detail=f"closes {proposal.voting_closes_at}",
    )
    voters = await _eligible_voters(session)
    await notifications.proposal_voting_opened(
        session, voters=voters, proposal_id=proposal.id, title=proposal.title
    )
    return proposal.status


# --- Edit (draft only) -----------------------------------------------------

async def update(
    session: AsyncSession, proposal, by_member, *, expected_version: Optional[int] = None, **fields
) -> None:
    """Edit a draft. Optimistic-lock via expected_version (the spec's requirement)."""
    if proposal.status != ProposalStatus.DRAFT:
        raise DomainError("Only a draft proposal can be edited.")
    if by_member.id != proposal.proposer_id:
        raise Forbidden("Only the proposer can edit this proposal.")
    if expected_version is not None and expected_version != proposal.version:
        raise Conflict("This proposal changed since you loaded it — reload and retry.")
    for key in ("title", "body", "proposed_category", "proposed_text", "proposed_amount"):
        if key in fields and fields[key] is not None:
            value = fields[key]
            if key in ("body", "proposed_text", "proposed_category"):
                value = clean(value, max_len=500 if key != "body" else 5000)
            setattr(proposal, key, value)


# --- Voting ----------------------------------------------------------------

async def vote(session: AsyncSession, proposal_id: int, voter_id: int, choice: str) -> dict:
    """Cast/replace a tenant's vote. Returns the live tally."""
    if choice not in (ProposalVoteChoice.YES, ProposalVoteChoice.NO, ProposalVoteChoice.ABSTAIN):
        raise Unprocessable("vote must be 'yes', 'no' or 'abstain'.")
    proposal = await proposals_repo.get(session, proposal_id)
    if proposal is None:
        raise NotFound("No such proposal.")
    if proposal.status != ProposalStatus.VOTING:
        raise DomainError("This proposal isn't open for voting.")
    if proposal.voting_closes_at and now_iso() >= proposal.voting_closes_at:
        raise DomainError("Voting has closed for this proposal.")
    voter = await members_repo.get(session, voter_id)
    if voter is None or not voter.is_active or voter.role != Role.TENANT:
        raise Forbidden("Only active tenants can vote on rule proposals.")

    await proposals_repo.record_vote(session, proposal_id, voter_id, choice)
    await proposals_repo.log_event(
        session, proposal_id=proposal_id, type=ProposalEventType.VOTE_CAST,
        actor_id=voter_id, detail=choice,
    )
    return await proposals_repo.vote_tally(session, proposal_id)


# --- Comments --------------------------------------------------------------

async def add_comment(
    session: AsyncSession, proposal_id: int, author, body: str, parent_id: Optional[int] = None
) -> int:
    proposal = await proposals_repo.get(session, proposal_id)
    if proposal is None:
        raise NotFound("No such proposal.")
    body = clean(body)
    if not body:
        raise Unprocessable("Comment can't be empty.")
    if parent_id is not None:
        parent = await proposals_repo.get_comment(session, parent_id)
        if parent is None or parent.proposal_id != proposal_id:
            raise DomainError("Parent comment not found on this proposal.")
    comment = await proposals_repo.add_comment(
        session, proposal_id=proposal_id, author_id=author.id, body=body, parent_id=parent_id
    )
    await proposals_repo.log_event(
        session, proposal_id=proposal_id, type=ProposalEventType.COMMENTED, actor_id=author.id
    )
    proposer = await members_repo.get(session, proposal.proposer_id)
    if proposer is not None and proposer.id != author.id:
        await notifications.proposal_commented(
            session, recipients=[proposer], proposal_id=proposal_id, by=author.name, title=proposal.title
        )
    return comment.id


async def edit_comment(session: AsyncSession, comment_id: int, by_member, body: str) -> None:
    comment = await proposals_repo.get_comment(session, comment_id)
    if comment is None or comment.deleted:
        raise NotFound("No such comment.")
    if comment.author_id != by_member.id:
        raise Forbidden("You can only edit your own comment.")
    cleaned = clean(body)
    if not cleaned:
        raise Unprocessable("Comment can't be empty.")
    comment.body = cleaned
    comment.edited_at = now_iso()


async def delete_comment(session: AsyncSession, comment_id: int, by_member) -> None:
    comment = await proposals_repo.get_comment(session, comment_id)
    if comment is None or comment.deleted:
        raise NotFound("No such comment.")
    if comment.author_id != by_member.id and by_member.role != Role.TENANT:
        raise Forbidden("You can only delete your own comment.")
    comment.deleted = True
    comment.body = ""


# --- Close + evaluate + merge ----------------------------------------------

async def close_and_evaluate(session: AsyncSession, proposal) -> str:
    """Tally the votes and apply the passing conditions. Idempotent: only acts
    while status is 'voting'. Merges into the rule book if it passes."""
    if proposal.status != ProposalStatus.VOTING:
        return proposal.status

    tally = await proposals_repo.vote_tally(session, proposal.id)
    eligible = len(await _eligible_voters(session))
    participation = tally["total"]
    decided = tally["yes"] + tally["no"]
    yes_pct = round(100 * tally["yes"] / decided) if decided else 0

    await proposals_repo.log_event(
        session, proposal_id=proposal.id, type=ProposalEventType.VOTING_CLOSED,
        detail=f"yes {tally['yes']} · no {tally['no']} · abstain {tally['abstain']} · eligible {eligible}",
    )

    if participation < settings.proposal_quorum:
        return await _finalize(
            session, proposal, ProposalStatus.EXPIRED, ProposalEventType.EXPIRED,
            f"no quorum ({participation}/{settings.proposal_quorum})",
        )
    passed = yes_pct >= settings.proposal_pass_pct and tally["yes"] >= settings.proposal_min_yes
    if not passed:
        return await _finalize(
            session, proposal, ProposalStatus.REJECTED, ProposalEventType.REJECTED,
            f"{yes_pct}% yes (<{settings.proposal_pass_pct}% or <{settings.proposal_min_yes} yes)",
        )
    await _merge(session, proposal)
    return await _finalize(
        session, proposal, ProposalStatus.PASSED, ProposalEventType.PASSED,
        f"{yes_pct}% yes → merged",
    )


async def _finalize(session, proposal, status, event_type, detail) -> str:
    proposal.status = status
    proposal.resolved_at = now_iso()
    proposal.resolution_detail = detail
    await proposals_repo.log_event(
        session, proposal_id=proposal.id, type=event_type, detail=detail
    )
    proposer = await members_repo.get(session, proposal.proposer_id)
    recipients = [proposer] if proposer else []
    if status == ProposalStatus.PASSED:
        title = "✅ Your rule proposal passed"
        body = f"“{proposal.title}” passed ({detail}) and is now in the rule book."
        # Tell everyone a new rule shipped.
        recipients = await members_repo.list_active(session)
        kind = "rule_published"
    elif status == ProposalStatus.EXPIRED:
        title, body, kind = "⌛ Proposal expired", f"“{proposal.title}” didn't reach quorum.", "proposal_resolved"
    else:
        title, body, kind = "🗳️ Proposal rejected", f"“{proposal.title}” was voted down ({detail}).", "proposal_resolved"
    if recipients:
        await notifications.proposal_resolved(
            session, recipients=recipients, proposal_id=proposal.id, title=title, body=body, kind=kind
        )
    return status


async def _merge(session: AsyncSession, proposal, approved_by: Optional[int] = None) -> None:
    """Apply a passed proposal to the rule book + snapshot an immutable version."""
    if proposal.type == ProposalType.NEW_RULE:
        rule = await rules_repo.add(
            session,
            category=proposal.proposed_category or "general",
            text=proposal.proposed_text,
            fine_amount=proposal.proposed_amount or 0,
        )
        active = True
    else:
        rule = await rules_repo.get(session, proposal.target_rule_id)
        if rule is None:
            raise DomainError("Target rule vanished before merge.")
        if proposal.type == ProposalType.MODIFY_RULE:
            if proposal.proposed_category:
                rule.category = proposal.proposed_category
            if proposal.proposed_text:
                rule.text = proposal.proposed_text
            if proposal.proposed_amount is not None:
                rule.fine_amount = proposal.proposed_amount
            active = True
        else:  # DELETE_RULE
            rule.is_active = False
            active = False

    version = await rule_versions_repo.insert(
        session,
        rule_id=rule.id,
        version_number=await rule_versions_repo.next_version_number(session, rule.id),
        category=rule.category,
        text=rule.text,
        fine_amount=rule.fine_amount,
        is_favorite=rule.is_favorite,
        severity_tier=rule.severity_tier,
        auto_confirm=rule.auto_confirm,
        active=active,
        created_by=proposal.proposer_id,
        approved_by=approved_by,
        proposal_id=proposal.id,
    )
    proposal.merged_rule_id = rule.id
    proposal.merged_rule_version_id = version.id
    await proposals_repo.log_event(
        session, proposal_id=proposal.id, type=ProposalEventType.MERGED,
        detail=f"rule {rule.id} v{version.version_number}",
    )


async def sweep_due(session: AsyncSession) -> list[int]:
    """Close + evaluate every voting proposal whose window has elapsed."""
    closed = []
    for proposal_id in await proposals_repo.due_ids(session, now_iso()):
        proposal = await proposals_repo.get(session, proposal_id)
        if proposal is None:
            continue
        await close_and_evaluate(session, proposal)
        closed.append(proposal_id)
    return closed


# --- Admin actions (tenant) ------------------------------------------------

async def approve(session: AsyncSession, proposal_id: int, by_member) -> str:
    _require_admin(by_member)
    proposal = await proposals_repo.get(session, proposal_id)
    if proposal is None:
        raise NotFound("No such proposal.")
    if proposal.status != ProposalStatus.PENDING_REVIEW:
        raise DomainError("Only a proposal pending review can be approved.")
    await proposals_repo.log_event(
        session, proposal_id=proposal.id, type=ProposalEventType.APPROVED, actor_id=by_member.id
    )
    return await _open_voting(session, proposal)


async def reject(session: AsyncSession, proposal_id: int, by_member) -> str:
    _require_admin(by_member)
    proposal = await proposals_repo.get(session, proposal_id)
    if proposal is None:
        raise NotFound("No such proposal.")
    if proposal.status not in (ProposalStatus.PENDING_REVIEW, ProposalStatus.DRAFT):
        raise DomainError("Only a draft / pending proposal can be rejected outright.")
    return await _finalize(session, proposal, ProposalStatus.REJECTED, ProposalEventType.REJECTED, "rejected by admin")


async def extend(session: AsyncSession, proposal_id: int, by_member, hours: int) -> None:
    _require_admin(by_member)
    proposal = await proposals_repo.get(session, proposal_id)
    if proposal is None:
        raise NotFound("No such proposal.")
    if proposal.status != ProposalStatus.VOTING or not proposal.voting_closes_at:
        raise DomainError("Only an open vote can be extended.")
    if hours <= 0:
        raise Unprocessable("Extension must be a positive number of hours.")
    from datetime import datetime, timezone
    base = datetime.strptime(proposal.voting_closes_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    proposal.voting_closes_at = deadline_iso(base, hours)
    await proposals_repo.log_event(
        session, proposal_id=proposal.id, type=ProposalEventType.EXTENDED,
        actor_id=by_member.id, detail=f"+{hours}h → {proposal.voting_closes_at}",
    )


async def freeze(session: AsyncSession, proposal_id: int, by_member, frozen: bool) -> None:
    _require_admin(by_member)
    proposal = await proposals_repo.get(session, proposal_id)
    if proposal is None:
        raise NotFound("No such proposal.")
    proposal.frozen = frozen
    await proposals_repo.log_event(
        session, proposal_id=proposal.id, type=ProposalEventType.FROZEN,
        actor_id=by_member.id, detail="frozen" if frozen else "unfrozen",
    )


async def cancel(session: AsyncSession, proposal_id: int, by_member) -> str:
    proposal = await proposals_repo.get(session, proposal_id)
    if proposal is None:
        raise NotFound("No such proposal.")
    if by_member.id != proposal.proposer_id and by_member.role != Role.TENANT:
        raise Forbidden("Only the proposer or an admin can cancel this.")
    if proposal.status in (ProposalStatus.PASSED, ProposalStatus.REJECTED, ProposalStatus.EXPIRED, ProposalStatus.CANCELLED):
        raise DomainError("This proposal is already resolved.")
    proposal.status = ProposalStatus.CANCELLED
    proposal.resolved_at = now_iso()
    await proposals_repo.log_event(
        session, proposal_id=proposal.id, type=ProposalEventType.CANCELLED, actor_id=by_member.id
    )
    return proposal.status


async def force_merge(session: AsyncSession, proposal_id: int, by_member) -> str:
    """Admin override: merge a proposal regardless of the vote (e.g. consensus offline)."""
    _require_admin(by_member)
    proposal = await proposals_repo.get(session, proposal_id)
    if proposal is None:
        raise NotFound("No such proposal.")
    if proposal.status not in (ProposalStatus.VOTING, ProposalStatus.PENDING_REVIEW):
        raise DomainError("Only an in-flight proposal can be force-merged.")
    await _merge(session, proposal, approved_by=by_member.id)
    return await _finalize(session, proposal, ProposalStatus.PASSED, ProposalEventType.PASSED, "force-merged by admin")


# --- Detail (assembled for the API) ----------------------------------------

async def get_detail(session: AsyncSession, proposal_id: int, viewer) -> dict:
    proposal = await proposals_repo.get(session, proposal_id)
    if proposal is None:
        raise NotFound("No such proposal.")
    proposer = await members_repo.get(session, proposal.proposer_id)
    tally = await proposals_repo.vote_tally(session, proposal_id)
    eligible = len(await _eligible_voters(session))
    my_vote = await proposals_repo.get_vote(session, proposal_id, viewer.id)
    is_admin = viewer.role == Role.TENANT
    open_voting = proposal.status == ProposalStatus.VOTING
    return {
        "proposal": proposal,
        "proposer": proposer,
        "tally": tally,
        "eligible": eligible,
        "my_vote": my_vote.choice if my_vote else None,
        "comments": await proposals_repo.list_comments(session, proposal_id),
        "events": await proposals_repo.list_events(session, proposal_id),
        "can_vote": open_voting and viewer.role == Role.TENANT,
        "can_edit": proposal.status == ProposalStatus.DRAFT and proposal.proposer_id == viewer.id,
        "can_admin": is_admin,
    }
