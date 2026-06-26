"""Fine / complaint data access — the aggregate, its children, and reporting.

Writes here are *factory* helpers (insert_*, log_event, record_vote). Status
transitions are done by the service mutating loaded entities; the session
persists them. Reporting aggregates return numbers or explicit Row tuples.
"""

from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import Row, case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models import Fine, FineEvent, FineProof, FineVote, Member, Rule
from app.domain.enums import FineStatus, OWED_STATUSES, Resolution
from app.domain.time import now_iso
from app.repositories import fits_i64


# --- Fine entity -----------------------------------------------------------

async def get(session: AsyncSession, fine_id) -> Optional[Fine]:
    if not fits_i64(fine_id):
        return None
    return await session.get(Fine, fine_id)


async def insert(
    session: AsyncSession,
    *,
    member_id: int,
    rule_id: Optional[int],
    amount: int,
    added_by: int,
    status: str,
    ts: str,
    confirm_deadline: Optional[str],
) -> Fine:
    fine = Fine(
        member_id=member_id,
        rule_id=rule_id,
        amount=amount,
        added_by=added_by,
        status=status,
        ts=ts,
        confirm_deadline=confirm_deadline,
    )
    session.add(fine)
    await session.flush()
    return fine


async def bulk_auto_confirm(session: AsyncSession, now_iso_str: str) -> list[int]:
    """Atomically promote overdue, still-pending complaints to confirmed and
    RETURN exactly the ids changed — so the result can't drift even if a dispute
    lands concurrently (one statement holds the write lock)."""
    stmt = (
        update(Fine)
        .where(
            Fine.status == FineStatus.PENDING,
            Fine.confirm_deadline.is_not(None),
            Fine.confirm_deadline < now_iso_str,
        )
        .values(
            status=FineStatus.CONFIRMED,
            resolution=Resolution.AUTO_CONFIRMED,
            resolved_at=now_iso_str,
        )
        .returning(Fine.id)
        .execution_options(synchronize_session=False)
    )
    return [row[0] for row in (await session.execute(stmt)).all()]


async def due_vote_ids(session: AsyncSession, now_iso_str: str) -> list[int]:
    """Ids of disputed complaints whose vote window has closed."""
    return list(
        await session.scalars(
            select(Fine.id).where(
                Fine.status == FineStatus.DISPUTED,
                Fine.vote_deadline.is_not(None),
                Fine.vote_deadline < now_iso_str,
            )
        )
    )


async def recent(session: AsyncSession, limit: int = 20) -> Sequence[Row]:
    """Recent complaints with accused/accuser names + rule text (for the dashboard)."""
    accused = aliased(Member)
    accuser = aliased(Member)
    stmt = (
        select(
            Fine.id,
            Fine.amount,
            Fine.status,
            Fine.paid,
            Fine.ts,
            accused.name.label("member_name"),
            accuser.name.label("accuser_name"),
            Rule.text.label("rule_text"),
        )
        .join(accused, accused.id == Fine.member_id)
        .join(accuser, accuser.id == Fine.added_by)
        .outerjoin(Rule, Rule.id == Fine.rule_id)
        .order_by(Fine.ts.desc())
        .limit(limit)
    )
    return (await session.execute(stmt)).all()


# --- Proof -----------------------------------------------------------------

async def insert_proof(
    session: AsyncSession,
    *,
    fine_id: int,
    uploaded_by: Optional[int],
    source: str,
    ref: str,
    content_type: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> FineProof:
    proof = FineProof(
        fine_id=fine_id,
        uploaded_by=uploaded_by,
        source=source,
        ref=ref,
        content_type=content_type,
        width=width,
        height=height,
    )
    session.add(proof)
    await session.flush()
    return proof


async def list_proofs(session: AsyncSession, fine_id: int) -> list[FineProof]:
    return list(
        await session.scalars(
            select(FineProof).where(FineProof.fine_id == fine_id).order_by(FineProof.id)
        )
    )


async def get_proof(session: AsyncSession, proof_id) -> Optional[FineProof]:
    if not fits_i64(proof_id):
        return None
    return await session.get(FineProof, proof_id)


# --- Audit trail -----------------------------------------------------------

async def log_event(
    session: AsyncSession,
    *,
    fine_id: int,
    type: str,
    actor_id: Optional[int] = None,
    detail: Optional[str] = None,
) -> FineEvent:
    event = FineEvent(fine_id=fine_id, type=type, actor_id=actor_id, detail=detail)
    session.add(event)
    await session.flush()
    return event


async def list_events(session: AsyncSession, fine_id: int) -> Sequence[Row]:
    """The timeline, oldest first, with actor names for display."""
    stmt = (
        select(
            FineEvent.type,
            FineEvent.detail,
            FineEvent.ts,
            Member.name.label("actor_name"),
        )
        .outerjoin(Member, Member.id == FineEvent.actor_id)
        .where(FineEvent.fine_id == fine_id)
        .order_by(FineEvent.ts, FineEvent.id)
    )
    return (await session.execute(stmt)).all()


# --- Votes -----------------------------------------------------------------

async def get_vote(
    session: AsyncSession, fine_id: int, voter_id: int
) -> Optional[FineVote]:
    return await session.scalar(
        select(FineVote).where(FineVote.fine_id == fine_id, FineVote.voter_id == voter_id)
    )


async def record_vote(
    session: AsyncSession, fine_id: int, voter_id: int, vote: str
) -> None:
    """Cast or change a vote (one per voter per fine; latest wins)."""
    existing = await get_vote(session, fine_id, voter_id)
    if existing is None:
        session.add(FineVote(fine_id=fine_id, voter_id=voter_id, vote=vote))
    else:
        existing.vote = vote
        existing.ts = now_iso()
    await session.flush()


async def vote_tally(session: AsyncSession, fine_id: int) -> dict:
    stmt = select(
        func.coalesce(func.sum(case((FineVote.vote == "uphold", 1), else_=0)), 0).label("uphold"),
        func.coalesce(func.sum(case((FineVote.vote == "void", 1), else_=0)), 0).label("void"),
        func.count().label("total"),
    ).where(FineVote.fine_id == fine_id)
    row = (await session.execute(stmt)).one()
    return {"uphold": row.uphold, "void": row.void, "total": row.total}


# --- Reporting / money aggregates ------------------------------------------

async def pot_total(session: AsyncSession) -> int:
    return await session.scalar(
        select(func.coalesce(func.sum(Fine.amount), 0)).where(Fine.status.in_(OWED_STATUSES))
    )


async def owed_count(session: AsyncSession) -> int:
    return await session.scalar(
        select(func.count()).select_from(Fine).where(Fine.status.in_(OWED_STATUSES))
    )


async def fines_owed_by(session: AsyncSession, member_id: int) -> int:
    return await session.scalar(
        select(func.coalesce(func.sum(Fine.amount), 0)).where(
            Fine.member_id == member_id,
            Fine.paid.is_(False),
            Fine.status.in_(OWED_STATUSES),
        )
    )


async def list_unpaid_owed(session: AsyncSession, member_id: int) -> Sequence[Row]:
    stmt = (
        select(Fine.id, Fine.amount, Rule.text.label("rule_text"))
        .outerjoin(Rule, Rule.id == Fine.rule_id)
        .where(
            Fine.member_id == member_id,
            Fine.paid.is_(False),
            Fine.status.in_(OWED_STATUSES),
        )
        .order_by(Fine.ts)
    )
    return (await session.execute(stmt)).all()


async def hall_of_shame(session: AsyncSession, limit: int = 10) -> list[dict]:
    total = func.coalesce(func.sum(Fine.amount), 0)
    stmt = (
        select(Member.name, func.count(Fine.id).label("fines"), total.label("total"))
        .join(Fine, Fine.member_id == Member.id)
        .where(Member.is_active.is_(True), Fine.status.in_(OWED_STATUSES))
        .group_by(Member.id, Member.name)
        .order_by(total.desc(), func.count(Fine.id).desc())
        .limit(limit)
    )
    return [
        {"name": r.name, "fines": r.fines, "total": r.total}
        for r in (await session.execute(stmt)).all()
    ]


async def overturn_rows(session: AsyncSession) -> Sequence[Row]:
    """Per active member: complaints filed, still-standing, overturned. The rate
    is computed in the reporting service (presentation), not here."""
    upheld = func.coalesce(func.sum(case((Fine.status.in_(("confirmed", "upheld")), 1), else_=0)), 0)
    overturned = func.coalesce(func.sum(case((Fine.status.in_(("void", "disputed")), 1), else_=0)), 0)
    stmt = (
        select(
            Member.name,
            func.count(Fine.id).label("filed"),
            upheld.label("upheld"),
            overturned.label("overturned"),
        )
        .select_from(Member)
        .outerjoin(Fine, Fine.added_by == Member.id)
        .where(Member.is_active.is_(True))
        .group_by(Member.id, Member.name)
        .order_by(overturned.desc(), func.count(Fine.id).desc())
    )
    return (await session.execute(stmt)).all()


# --- Anti-spam -------------------------------------------------------------

async def count_since(session: AsyncSession, added_by: int, since_iso: str) -> int:
    return await session.scalar(
        select(func.count())
        .select_from(Fine)
        .where(Fine.added_by == added_by, Fine.ts >= since_iso)
    )


async def find_recent_duplicate(
    session: AsyncSession,
    added_by: int,
    accused_id: int,
    rule_id: Optional[int],
    since_iso: str,
) -> Optional[Fine]:
    """Same accuser+accused+rule, still live, within the window. Null rule (ad-hoc)
    never matches."""
    if rule_id is None:
        return None
    return await session.scalar(
        select(Fine)
        .where(
            Fine.added_by == added_by,
            Fine.member_id == accused_id,
            Fine.rule_id == rule_id,
            Fine.ts >= since_iso,
            Fine.status != FineStatus.VOID,
        )
        .order_by(Fine.ts.desc())
        .limit(1)
    )
