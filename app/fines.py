"""Fine lifecycle — the status workflow lives here, nowhere else.

A fine is a *claim, not a verdict* (DESIGN.md). v1 ships Layer 1 only:

        ┌──── Dispute (one tap, while pending) ──► disputed ──(humans)──► upheld | void
 pending┤
        └──── cooling window elapses, undisputed (sweep) ──► confirmed

Every transition of `fines.status` goes through a function in this module so the
rules below have a single home. `queries.py` stays plain data-access; the policy
(cooling window, who-can-do-what) is here.

Business rules enforced (see plans/v1/business-rules.md):
  BR-021  creating a fine bumps the rule's use_count
  BR-030  status only moves pending → confirmed | disputed | void | upheld
  BR-031  a new fine is pending with confirm_deadline = now + COOLING_HOURS
  BR-032  sweep promotes pending → confirmed iff confirm_deadline < now (never disputed)
  BR-033  dispute is one tap, allowed only while pending; no penalty in v1
  BR-034  accuser (added_by) and accused (member_id) must differ
  BR-036  paid is independent of status
  BR-037  amount is snapshotted onto the fine at creation
"""

from __future__ import annotations

from typing import Optional

import aiosqlite

from . import queries
from .config import settings
from .db import deadline_iso, iso, now, now_iso


class FineError(ValueError):
    """A fine action that can't proceed (bad input or wrong state).

    Subclasses ValueError so callers that only catch ValueError still work.
    """


# --- Create ----------------------------------------------------------------

async def create_fine(
    db: aiosqlite.Connection,
    *,
    accused_id: int,
    added_by: int,
    rule_id: Optional[int] = None,
    amount: Optional[int] = None,
) -> int:
    """Report a fine. Returns the new fine id.

    Starts `pending` with a cooling deadline (BR-031). The amount is snapshotted:
    if not given explicitly it's copied from the rule's current `fine_amount`
    (BR-037), so later rule edits never rewrite this fine.

    Raises FineError on self-fine (BR-034), unknown rule/members, a fine with
    neither rule nor amount, or a negative amount.
    """
    if accused_id == added_by:
        raise FineError("You can't fine yourself — accuser and accused must differ.")

    # Both parties must be present, active flatmates. The bot's pickers already
    # only offer active tenants, but this service is the single home for the rule
    # (BR-001/034) — so guard here too, or an ex-tenant's fine could sweep into
    # the pot. (Whether guests are finable is a v2 decision — BR-002.)
    accused = await queries.get_member(db, accused_id)
    if accused is None:
        raise FineError(f"Unknown accused member: {accused_id}.")
    if not accused["is_active"]:
        raise FineError("Can't fine a member who isn't active in the flat.")
    accuser = await queries.get_member(db, added_by)
    if accuser is None:
        raise FineError(f"Unknown reporting member: {added_by}.")
    if not accuser["is_active"]:
        raise FineError("Only an active flatmate can report a fine.")

    rule = None
    if rule_id is not None:
        rule = await queries.get_rule(db, rule_id)
        if rule is None:
            raise FineError(f"Unknown rule: {rule_id}.")

    # Snapshot the amount (BR-037). Explicit amount wins (ad-hoc fine); otherwise
    # take it from the rule. A fine with neither is meaningless.
    if amount is None:
        if rule is None:
            raise FineError("A fine needs either a rule or an explicit amount.")
        amount = rule["fine_amount"]
    if amount < 0:
        raise FineError("A fine amount can't be negative.")

    # One clock read for both timestamps so confirm_deadline == ts + COOLING_HOURS
    # exactly (BR-031).
    created = now()
    fine_id = await queries.insert_fine(
        db,
        member_id=accused_id,
        rule_id=rule_id,
        amount=amount,
        added_by=added_by,
        status="pending",
        ts=iso(created),
        confirm_deadline=deadline_iso(created, settings.cooling_hours),  # BR-031
    )

    # Self-tune which rules bubble up (BR-021). Only when a rule was cited.
    if rule_id is not None:
        await queries.bump_rule_use(db, rule_id)

    return fine_id


# --- Cooling-window sweep --------------------------------------------------

async def sweep_due(db: aiosqlite.Connection) -> list[int]:
    """Promote overdue, undisputed pending fines to `confirmed` (BR-032).

    Returns the ids actually promoted (handy for notifications later). Because
    `disputed` is a distinct status, filtering on `status='pending'` already
    excludes disputed fines — they are never auto-confirmed.

    One atomic `UPDATE ... RETURNING` does the promotion and reports exactly the
    rows it changed, so the return value can't drift from reality even if a fine
    is disputed concurrently (a single statement holds the write lock).
    """
    async with db.execute(
        "UPDATE fines SET status = 'confirmed' "
        "WHERE status = 'pending' AND confirm_deadline IS NOT NULL "
        "AND confirm_deadline < ? "
        "RETURNING id",
        (now_iso(),),
    ) as cur:
        promoted = [row["id"] for row in await cur.fetchall()]
    await db.commit()
    return promoted


# --- One-tap actions (thin, guarded wrappers) ------------------------------

async def dispute(
    db: aiosqlite.Connection, fine_id: int, reason: Optional[str] = None
) -> bool:
    """Dispute a fine. Returns True if it moved to `disputed`.

    Only a `pending` fine can be disputed in v1 (BR-033) — once it has confirmed,
    contesting it is a human/v3 matter. Returns False (not an error) if the fine
    is no longer pending, so the bot can say "too late, it's already confirmed."
    """
    fine = await queries.get_fine(db, fine_id)
    if fine is None:
        raise FineError(f"Unknown fine: {fine_id}.")
    if fine["status"] != "pending":
        return False
    await queries.dispute_fine(db, fine_id, reason)
    return True


async def mark_paid(db: aiosqlite.Connection, fine_id: int) -> bool:
    """Record that a fine was paid into the jar (BR-036). Returns True iff it
    flipped unpaid → paid (so the bot can tell a real change from a double-tap).

    Only a `confirmed`/`upheld` fine — one that actually counts as owed money —
    can be marked paid. Paying a still-`pending` fine would desync the ledger:
    once it later sweeps to `confirmed` it would land in the pot yet never show in
    dues (already paid). `paid` stays independent of `status` (this never changes
    the status); it's a bookkeeping record, not a money movement (BR-000).
    """
    fine = await queries.get_fine(db, fine_id)
    if fine is None:
        raise FineError(f"Unknown fine: {fine_id}.")
    if fine["status"] not in queries.OWED_STATUSES:
        raise FineError("Only a confirmed fine can be marked paid.")
    if fine["paid"]:
        return False
    await queries.mark_fine_paid(db, fine_id)
    return True
