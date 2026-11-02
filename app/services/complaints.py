"""Complaint lifecycle — the status workflow lives here, nowhere else.

A fine *is* a complaint with mandatory image proof:

                         accused accepts
   raised ───────────────────────────────────────► REGISTERED (confirmed)
  (pending)                                        ▲
     │ accused/anyone denies ──► vote opens        │ cooling window elapses (sweep)
     ▼   (status='disputed' + vote_deadline)       │ resolution=auto_confirmed
   VOTING ── majority uphold ─────────────────────►┘ REGISTERED (upheld)
     │   └── majority void / tie / no quorum ──────► REJECTED (void)

Every transition mutates the loaded Fine + appends a `fine_events` audit row +
fans a notification out. Repositories do the reads/inserts; the session (request
or sweep scope) owns the transaction. Business-rule violations raise DomainError.
"""

from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import DomainError, Forbidden, NotFound
from app.domain.enums import (
    OWED_STATUSES,
    PAYABLE_STATUSES,
    EventType,
    FineStatus,
    PaymentStatus,
    Resolution,
    Vote,
)
from app.domain.time import deadline_iso, iso, now, now_iso
from app.repositories import fines as fines_repo
from app.repositories import members as members_repo
from app.repositories import rules as rules_repo
from app.services import notifications

# A proof is a dict: {source, ref, content_type?, width?, height?, uploaded_by?}.
Proof = dict


def rupees(n: int) -> str:
    return f"₹{n:,}"


# --- Payment lifecycle (Bug 2: registration creates a debt; it never settles) ---

async def _register_obligation(session: AsyncSession, fine) -> None:
    """A fine has just been REGISTERED (accepted / auto-confirmed / upheld). Move it into
    the payment lifecycle: OWED, with a pay-by countdown. Acceptance acknowledges
    responsibility only — the debt is now pending payment, NOT settled."""
    if fine.payment_status != PaymentStatus.NOT_OWED:
        return
    fine.payment_status = PaymentStatus.OWED
    fine.pay_by = deadline_iso(now(), settings.payment_window_hours)
    await fines_repo.log_event(
        session, fine_id=fine.id, type=EventType.PAYMENT_DUE,
        detail=f"registered — pay by {fine.pay_by}",
    )


# --- Authorization (one source of truth for who may act on a complaint) ------

def allowed_actions(fine, viewer_id: int) -> dict:
    """The single source of truth for who may act on a complaint. Feeds BOTH the wire
    `can_*` flags (get_detail) and the service-layer enforcement guards, so the two can
    never drift apart.

    Only the **accused** may respond to a pending complaint — Accept, Deny, or Ignore
    (Ignore = take no action; the cooling sweep then auto-confirms). Denying opens a
    neutral-member vote, on which only members who are neither accuser nor accused may
    vote. (This replaced the earlier "anyone may Deny" rule.)"""
    is_accused = fine.member_id == viewer_id
    pending = fine.status == FineStatus.PENDING
    return {
        "can_accept": pending and is_accused,
        "can_dispute": pending and is_accused,
        "can_vote": (
            fine.status == FineStatus.DISPUTED
            and viewer_id not in (fine.added_by, fine.member_id)
        ),
    }


# --- Create ----------------------------------------------------------------

async def create(
    session: AsyncSession,
    *,
    accused_id: int,
    added_by: int,
    proofs: Sequence[Proof],
    rule_id: Optional[int] = None,
    amount: Optional[int] = None,
) -> int:
    """Raise a complaint. Returns the new fine id. Requires >=1 proof; notifies
    the accused; enforces anti-spam guards."""
    if not proofs:
        raise DomainError("A complaint needs at least one photo as proof.")
    if accused_id == added_by:
        raise DomainError("You can't complain about yourself — accuser and accused must differ.")

    accused = await members_repo.get(session, accused_id)
    if accused is None:
        raise DomainError(f"Unknown accused member: {accused_id}.")
    if not accused.is_active:
        raise DomainError("Can't complain about a member who isn't active in the flat.")
    accuser = await members_repo.get(session, added_by)
    if accuser is None:
        raise DomainError(f"Unknown reporting member: {added_by}.")
    if not accuser.is_active:
        raise DomainError("Only an active flatmate can file a complaint.")

    rule = await rules_repo.get(session, rule_id) if rule_id is not None else None
    if rule_id is not None and rule is None:
        raise DomainError(f"Unknown rule: {rule_id}.")

    if amount is None:
        if rule is None:
            raise DomainError("A complaint needs either a rule or an explicit amount.")
        amount = rule.fine_amount
    if amount < 0:
        raise DomainError("A fine amount can't be negative.")

    await _check_anti_spam(session, added_by=added_by, accused_id=accused_id, rule_id=rule_id)

    created = now()  # one clock read so confirm_deadline == ts + COOLING_HOURS exactly
    fine = await fines_repo.insert(
        session,
        member_id=accused_id,
        rule_id=rule_id,
        amount=amount,
        added_by=added_by,
        status=FineStatus.PENDING,
        ts=iso(created),
        confirm_deadline=deadline_iso(created, settings.cooling_hours),
    )
    for proof in proofs:
        await fines_repo.insert_proof(
            session,
            fine_id=fine.id,
            uploaded_by=proof.get("uploaded_by", added_by),
            source=proof["source"],
            ref=proof["ref"],
            content_type=proof.get("content_type"),
            width=proof.get("width"),
            height=proof.get("height"),
        )
    if rule is not None:
        rule.use_count += 1  # self-tune favorites

    reason = rule.text if rule else "(no specific rule)"
    await fines_repo.log_event(
        session, fine_id=fine.id, type=EventType.RAISED, actor_id=added_by,
        detail=f"{reason} · {amount} · {len(proofs)} proof(s)",
    )
    await notifications.complaint_raised(
        session, accused=accused, accuser_name=accuser.name, reason=reason,
        amount=amount, fine_id=fine.id, cooling_hours=settings.cooling_hours,
    )
    await fines_repo.log_event(
        session, fine_id=fine.id, type=EventType.ACCUSED_NOTIFIED, detail=accused.name
    )
    return fine.id


async def _check_anti_spam(
    session: AsyncSession, *, added_by: int, accused_id: int, rule_id: Optional[int]
) -> None:
    if settings.max_complaints_per_day > 0:
        since = deadline_iso(now(), -24)
        if await fines_repo.count_since(session, added_by, since) >= settings.max_complaints_per_day:
            raise DomainError(
                f"You've hit the limit of {settings.max_complaints_per_day} complaints "
                f"in 24h. Take a breather."
            )
    if settings.duplicate_window_hours > 0 and rule_id is not None:
        since = deadline_iso(now(), -settings.duplicate_window_hours)
        if await fines_repo.find_recent_duplicate(session, added_by, accused_id, rule_id, since):
            raise DomainError(
                "You already filed this same complaint recently — give it time to resolve."
            )


# --- Accept ----------------------------------------------------------------

async def accept(session: AsyncSession, fine_id: int, by_member: int) -> bool:
    """Accused accepts -> registered (confirmed), no vote. True iff it moved."""
    fine = await fines_repo.get(session, fine_id)
    if fine is None:
        raise DomainError(f"Unknown complaint: {fine_id}.")
    if fine.member_id != by_member:
        raise Forbidden("Only the accused can accept a complaint.")
    if fine.status != FineStatus.PENDING:
        return False

    fine.status = FineStatus.CONFIRMED
    fine.resolution = Resolution.ACCEPTED
    fine.resolved_at = now_iso()
    await fines_repo.log_event(session, fine_id=fine_id, type=EventType.ACCEPTED, actor_id=by_member)
    await _register_obligation(session, fine)  # -> OWED (payment pending); NOT settled

    accused = await members_repo.get(session, fine.member_id)
    accuser = await members_repo.get(session, fine.added_by)
    await notifications.complaint_resolved(
        session, recipients=[m for m in (accuser, accused) if m is not None], fine_id=fine_id,
        title=f"✅ Complaint accepted — {rupees(fine.amount)}",
        body=(f"{accused.name if accused else 'The accused'} accepted responsibility. Registered — "
              f"now pay {rupees(fine.amount)} into the pot by {fine.pay_by}."),
        kind="complaint_registered",
    )
    return True


# --- Dispute / Deny -> open a vote -----------------------------------------

async def dispute(
    session: AsyncSession, fine_id: int, by_member: Optional[int] = None,
    reason: Optional[str] = None,
) -> bool:
    """Deny -> open a neutral-member vote (or void if there are no eligible
    voters). Only the accused may deny (enforced here AND at the route). True iff it
    moved out of pending."""
    fine = await fines_repo.get(session, fine_id)
    if fine is None:
        raise DomainError(f"Unknown complaint: {fine_id}.")
    if by_member is None or fine.member_id != by_member:
        raise Forbidden("Only the accused can deny this complaint.")
    if fine.status != FineStatus.PENDING:
        return False

    voters = await members_repo.eligible_voters(session, fine.added_by, fine.member_id)
    accuser = await members_repo.get(session, fine.added_by)
    accused = await members_repo.get(session, fine.member_id)
    rule = await rules_repo.get(session, fine.rule_id) if fine.rule_id else None
    reason_text = reason or (f"denied by {accused.name}" if accused else "denied")
    rule_text = rule.text if rule else "(no specific rule)"

    await fines_repo.log_event(
        session, fine_id=fine_id, type=EventType.DISPUTED, actor_id=by_member, detail=reason_text
    )

    if not voters:
        fine.status = FineStatus.VOID
        fine.resolution = Resolution.VOID
        fine.resolved_at = now_iso()
        await fines_repo.log_event(
            session, fine_id=fine_id, type=EventType.VOTE_FINALIZED,
            detail="no eligible voters → void",
        )
        await notifications.complaint_resolved(
            session, recipients=[m for m in (accuser, accused) if m is not None], fine_id=fine_id,
            title="⚖️ Complaint voided",
            body="It was denied and there's no neutral member to vote — dropped.",
        )
        return True

    deadline = deadline_iso(now(), settings.vote_window_hours)
    fine.status = FineStatus.DISPUTED
    fine.dispute_reason = reason_text
    fine.vote_deadline = deadline
    await fines_repo.log_event(
        session, fine_id=fine_id, type=EventType.VOTING_STARTED,
        detail=f"{len(voters)} eligible · closes {deadline}",
    )
    await notifications.vote_requested(
        session, voters=voters,
        accused_name=accused.name if accused else "the accused",
        accuser_name=accuser.name if accuser else "someone",
        reason=rule_text, amount=fine.amount, fine_id=fine_id,
    )
    await fines_repo.log_event(
        session, fine_id=fine_id, type=EventType.MEMBERS_NOTIFIED, detail=f"{len(voters)} voter(s)"
    )
    return True


# --- Vote ------------------------------------------------------------------

async def cast_vote(session: AsyncSession, fine_id: int, voter_id: int, choice: str) -> str:
    """Record/replace a neutral member's vote. Returns the resulting status
    ('disputed' = still open, or the finalized 'upheld'/'void')."""
    if choice not in (Vote.UPHOLD, Vote.VOID):
        raise DomainError("Vote must be 'uphold' or 'void'.")
    fine = await fines_repo.get(session, fine_id)
    if fine is None:
        raise DomainError(f"Unknown complaint: {fine_id}.")
    if fine.status != FineStatus.DISPUTED:
        raise DomainError("This complaint isn't open for voting.")
    if voter_id in (fine.added_by, fine.member_id):
        raise DomainError("The accuser and the accused can't vote on their own complaint.")
    voter = await members_repo.get(session, voter_id)
    if voter is None or not voter.is_active:
        raise DomainError("Only an active flatmate can vote.")

    await fines_repo.record_vote(session, fine_id, voter_id, choice)
    await fines_repo.log_event(
        session, fine_id=fine_id, type=EventType.VOTE_CAST, actor_id=voter_id, detail=choice
    )

    voters = await members_repo.eligible_voters(session, fine.added_by, fine.member_id)
    tally = await fines_repo.vote_tally(session, fine_id)
    if tally["total"] >= len(voters):
        return await finalize_vote(session, fine_id)
    return FineStatus.DISPUTED


async def finalize_vote(session: AsyncSession, fine_id: int) -> str:
    """Tally and close a vote: uphold > void -> upheld, else void (ties / no votes
    fall here — benefit of the doubt). Idempotent. Returns the final status."""
    fine = await fines_repo.get(session, fine_id)
    if fine is None:
        raise DomainError(f"Unknown complaint: {fine_id}.")
    if fine.status != FineStatus.DISPUTED:
        return fine.status  # already finalized (e.g. raced the sweep)

    tally = await fines_repo.vote_tally(session, fine_id)
    upheld = tally["uphold"] > tally["void"]
    status = FineStatus.UPHELD if upheld else FineStatus.VOID
    fine.status = status
    fine.resolution = Resolution.UPHELD if upheld else Resolution.VOID
    fine.resolved_at = now_iso()
    detail = f"uphold {tally['uphold']} · void {tally['void']} → {status}"
    await fines_repo.log_event(
        session, fine_id=fine_id, type=EventType.VOTE_FINALIZED, detail=detail
    )
    if upheld:
        await _register_obligation(session, fine)  # -> OWED (payment pending)

    accuser = await members_repo.get(session, fine.added_by)
    accused = await members_repo.get(session, fine.member_id)
    recipients = [m for m in (accuser, accused) if m is not None]
    if upheld:
        await notifications.complaint_resolved(
            session, recipients=recipients, fine_id=fine_id,
            title=f"✅ Complaint upheld — {rupees(fine.amount)}",
            body=f"The house voted to register it ({detail}).", kind="complaint_registered",
        )
    else:
        await notifications.complaint_resolved(
            session, recipients=recipients, fine_id=fine_id,
            title="⚖️ Complaint voided", body=f"The house voted to throw it out ({detail}).",
        )
    return status


# --- Sweeps (run together on the background interval) -----------------------

async def sweep_due(session: AsyncSession) -> list[int]:
    """Auto-confirm overdue, undisputed complaints (lazy consensus). Returns ids."""
    now_s = now_iso()
    promoted = await fines_repo.bulk_auto_confirm(session, now_s)
    for fine_id in promoted:
        await fines_repo.log_event(
            session, fine_id=fine_id, type=EventType.AUTO_CONFIRMED,
            detail="cooling window elapsed, undisputed",
        )
        fine = await fines_repo.get(session, fine_id)
        if fine is None:
            continue
        await _register_obligation(session, fine)  # -> OWED (payment pending)
        accused = await members_repo.get(session, fine.member_id)
        if accused is not None:
            await notifications.complaint_resolved(
                session, recipients=[accused], fine_id=fine_id,
                title=f"✅ Complaint auto-confirmed — {rupees(fine.amount)}",
                body=f"Nobody disputed it in time, so it's registered — pay {rupees(fine.amount)} by {fine.pay_by}.",
            )
    return promoted


async def sweep_votes(session: AsyncSession) -> list[int]:
    """Finalize every vote whose window has closed. Returns finalized ids."""
    due = await fines_repo.due_vote_ids(session, now_iso())
    for fine_id in due:
        await finalize_vote(session, fine_id)
    return due


# --- Pay -------------------------------------------------------------------

async def mark_paid(session: AsyncSession, fine_id: int) -> bool:
    """The accused marks a registered fine paid into the jar (a claim, not a transfer).
    Only an OWED/OVERDUE fine is payable. Settles immediately unless verification is on,
    in which case it awaits a verify step (MARKED_PAID -> SETTLED). Keeps the `paid`
    alias in sync. True iff it moved out of owed/overdue."""
    fine = await fines_repo.get(session, fine_id)
    if fine is None:
        raise DomainError(f"Unknown fine: {fine_id}.")
    if fine.payment_status not in PAYABLE_STATUSES:
        if fine.payment_status == PaymentStatus.NOT_OWED:
            raise DomainError("Only a registered fine can be marked paid.")
        return False  # already marked_paid / settled
    fine.payment_status = (
        PaymentStatus.MARKED_PAID if settings.payment_verification else PaymentStatus.SETTLED
    )
    fine.paid = True  # derived alias, kept in sync for existing queries/frontend
    fine.paid_at = now_iso()
    await fines_repo.log_event(session, fine_id=fine_id, type=EventType.PAID, actor_id=fine.member_id)
    return True


async def verify_paid(session: AsyncSession, fine_id: int) -> bool:
    """Confirm a self-attested payment (MARKED_PAID -> SETTLED). No-op unless verification
    is enabled and the fine is awaiting it. Reserved for the future verification UI."""
    fine = await fines_repo.get(session, fine_id)
    if fine is None:
        raise DomainError(f"Unknown fine: {fine_id}.")
    if fine.payment_status != PaymentStatus.MARKED_PAID:
        return False
    fine.payment_status = PaymentStatus.SETTLED
    await fines_repo.log_event(session, fine_id=fine_id, type=EventType.SETTLED)
    return True


async def sweep_overdue(session: AsyncSession) -> list[int]:
    """Move OWED fines whose pay-by has elapsed to OVERDUE (and remind the accused).
    Runs on the background sweep. Returns the ids moved."""
    overdue_ids = await fines_repo.due_payment_ids(session, now_iso())
    for fine_id in overdue_ids:
        fine = await fines_repo.get(session, fine_id)
        if fine is None:
            continue
        fine.payment_status = PaymentStatus.OVERDUE
        await fines_repo.log_event(
            session, fine_id=fine_id, type=EventType.OVERDUE, detail="payment window elapsed"
        )
        accused = await members_repo.get(session, fine.member_id)
        if accused is not None:
            await notifications.complaint_resolved(
                session, recipients=[accused], fine_id=fine_id,
                title=f"⏳ Fine overdue — {rupees(fine.amount)}",
                body="Your fine is past its pay-by date. Please pay it into the pot.",
                kind="fine_overdue",
            )
    return overdue_ids


async def owed_fines_for(session: AsyncSession, member_id: int, fine_ids: Sequence[int]) -> list:
    """The caller's own, currently-payable fines among `fine_ids` (deduped, validated).
    Raises if any id isn't the member's, or isn't an unpaid registered fine — so a UPI
    amount can only ever be built from a real, owed set the member actually holds."""
    out, seen = [], set()
    for fid in fine_ids:
        if fid in seen:
            continue
        seen.add(fid)
        fine = await fines_repo.get(session, fid)
        if fine is None or fine.member_id != member_id:
            raise NotFound("That's not your fine.")
        if fine.payment_status not in PAYABLE_STATUSES:
            raise DomainError("One of those fines isn't payable (not registered, or already paid).")
        out.append(fine)
    return out


async def mark_fines_paid(session: AsyncSession, member_id: int, fine_ids: Sequence[int]) -> dict:
    """Mark an explicit set of the caller's fines paid, each independently. Binds a
    payment to exactly the chosen fines (Bug 1: a per-fine payment can't settle others)."""
    if not fine_ids:
        raise DomainError("No fines selected to pay.")
    fines = await owed_fines_for(session, member_id, fine_ids)
    paid, total = [], 0
    for fine in fines:
        if await mark_paid(session, fine.id):
            paid.append(fine.id)
            total += fine.amount
    return {"paid": paid, "count": len(paid), "totalPaid": total}


# --- Detail (assembled view for the API) -----------------------------------

async def get_detail(session: AsyncSession, fine_id: int, viewer_id: int) -> dict:
    """Everything the complaint page shows. Raises NotFound if missing."""
    fine = await fines_repo.get(session, fine_id)
    if fine is None:
        raise NotFound("No such complaint.")
    accused = await members_repo.get(session, fine.member_id)
    accuser = await members_repo.get(session, fine.added_by)
    rule = await rules_repo.get(session, fine.rule_id) if fine.rule_id else None
    tally = await fines_repo.vote_tally(session, fine_id)
    eligible = await members_repo.eligible_voters(session, fine.added_by, fine.member_id)
    my_vote = await fines_repo.get_vote(session, fine_id, viewer_id)
    actions = allowed_actions(fine, viewer_id)
    return {
        "fine": fine,
        "accused": accused,
        "accuser": accuser,
        "rule_text": rule.text if rule else None,
        "tally": tally,
        "eligible_count": len(eligible),
        "my_vote": my_vote.vote if my_vote else None,
        "proofs": await fines_repo.list_proofs(session, fine_id),
        "events": await fines_repo.list_events(session, fine_id),
        **actions,
    }
