"""The ledger: all SQLite reads/writes and the money calcs.

The app records and calculates; it never holds or moves money. Every function
takes the connection explicitly so it's easy to call from the bot and the web.

Statuses that count toward what's "owed": confirmed + upheld.
"""

from __future__ import annotations

from typing import Optional

import aiosqlite

from .db import now_iso

# Fine statuses that count as real money owed / in the pot.
OWED_STATUSES = ("confirmed", "upheld")

# The only four bills this app splits (mirrors the schema CHECK). Closed by design.
BILL_TYPES = ("rent", "house_help", "electricity", "water")

# SQLite stores 64-bit signed ints; an id outside this range can't reference any
# row and would raise OverflowError on bind. id-lookups treat it as "not found"
# so a hand-crafted huge id from a web form is a clean miss, not a 500.
_I64_MIN, _I64_MAX = -(2**63), 2**63 - 1


def _fits_i64(value) -> bool:
    # isinstance guard so a forged/garbage id (e.g. a string from a tampered
    # session) is a clean miss, not a TypeError 500.
    return isinstance(value, int) and _I64_MIN <= value <= _I64_MAX


# --- Members ---------------------------------------------------------------

async def add_member(
    db: aiosqlite.Connection,
    name: str,
    telegram_id: Optional[int] = None,
    role: str = "tenant",
    host_id: Optional[int] = None,
) -> int:
    cur = await db.execute(
        "INSERT INTO members (name, telegram_id, role, joined_on, host_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (name, telegram_id, role, now_iso(), host_id),
    )
    await db.commit()
    return cur.lastrowid


async def get_member(db: aiosqlite.Connection, member_id: int) -> Optional[aiosqlite.Row]:
    if not _fits_i64(member_id):
        return None
    async with db.execute("SELECT * FROM members WHERE id = ?", (member_id,)) as cur:
        return await cur.fetchone()


async def get_member_by_telegram(
    db: aiosqlite.Connection, telegram_id: int
) -> Optional[aiosqlite.Row]:
    async with db.execute(
        "SELECT * FROM members WHERE telegram_id = ?", (telegram_id,)
    ) as cur:
        return await cur.fetchone()


async def link_telegram(db: aiosqlite.Connection, member_id: int, telegram_id: int) -> None:
    await db.execute(
        "UPDATE members SET telegram_id = ? WHERE id = ?", (telegram_id, member_id)
    )
    await db.commit()


async def list_active_tenants(db: aiosqlite.Connection) -> list[aiosqlite.Row]:
    async with db.execute(
        "SELECT * FROM members WHERE is_active = 1 AND role = 'tenant' ORDER BY name"
    ) as cur:
        return list(await cur.fetchall())


async def list_active_members(db: aiosqlite.Connection) -> list[aiosqlite.Row]:
    async with db.execute(
        "SELECT * FROM members WHERE is_active = 1 ORDER BY name"
    ) as cur:
        return list(await cur.fetchall())


async def has_any_member(db: aiosqlite.Connection) -> bool:
    """Whether the flat has *ever* had a member. Founder bootstrap keys off this
    (not active-only) so deactivating everyone can't re-trigger a new founder."""
    async with db.execute("SELECT 1 FROM members LIMIT 1") as cur:
        return await cur.fetchone() is not None


async def get_active_member_by_name(
    db: aiosqlite.Connection, name: str
) -> Optional[aiosqlite.Row]:
    """Case-insensitive lookup so /addtenant doesn't create duplicate rosters."""
    async with db.execute(
        "SELECT * FROM members WHERE is_active = 1 AND lower(name) = lower(?) "
        "ORDER BY id LIMIT 1",
        (name,),
    ) as cur:
        return await cur.fetchone()


# --- Web accounts (v2) -----------------------------------------------------

async def get_member_by_username(
    db: aiosqlite.Connection, username: str
) -> Optional[aiosqlite.Row]:
    async with db.execute(
        "SELECT * FROM members WHERE lower(username) = lower(?)", (username,)
    ) as cur:
        return await cur.fetchone()


async def register_member(
    db: aiosqlite.Connection, username: str, password_hash: str
) -> int:
    """Self-registration: a new active member, role='guest' (BR-A01). The
    username doubles as the display name until/unless changed."""
    cur = await db.execute(
        "INSERT INTO members (name, username, password_hash, role, joined_on) "
        "VALUES (?, ?, ?, 'guest', ?)",
        (username, username, password_hash, now_iso()),
    )
    await db.commit()
    return cur.lastrowid


async def set_role(db: aiosqlite.Connection, member_id: int, role: str) -> None:
    """Promote/demote (admin-only; the only path to the tenant role — BR-A03)."""
    await db.execute("UPDATE members SET role = ? WHERE id = ?", (role, member_id))
    await db.commit()


async def list_unlinked_tenants(db: aiosqlite.Connection) -> list[aiosqlite.Row]:
    """Active tenants who haven't linked a Telegram account yet — the people a
    new /start can offer to 'claim' (onboarding)."""
    async with db.execute(
        "SELECT * FROM members "
        "WHERE is_active = 1 AND role = 'tenant' AND telegram_id IS NULL "
        "ORDER BY name"
    ) as cur:
        return list(await cur.fetchall())


# --- Rules -----------------------------------------------------------------

async def add_rule(
    db: aiosqlite.Connection,
    category: str,
    text: str,
    fine_amount: int,
    is_favorite: bool = False,
    severity_tier: str = "low",
    auto_confirm: bool = True,
) -> int:
    cur = await db.execute(
        "INSERT INTO rules (category, text, fine_amount, is_favorite, "
        "severity_tier, auto_confirm) VALUES (?, ?, ?, ?, ?, ?)",
        (category, text, fine_amount, int(is_favorite), severity_tier, int(auto_confirm)),
    )
    await db.commit()
    return cur.lastrowid


async def get_rule(db: aiosqlite.Connection, rule_id: int) -> Optional[aiosqlite.Row]:
    if not _fits_i64(rule_id):
        return None
    async with db.execute("SELECT * FROM rules WHERE id = ?", (rule_id,)) as cur:
        return await cur.fetchone()


async def list_favorite_rules(db: aiosqlite.Connection, limit: int = 10) -> list[aiosqlite.Row]:
    # Favorites first, then whatever gets fined most — the rules people reach for.
    async with db.execute(
        "SELECT * FROM rules ORDER BY is_favorite DESC, use_count DESC, id LIMIT ?",
        (limit,),
    ) as cur:
        return list(await cur.fetchall())


async def list_categories(db: aiosqlite.Connection) -> list[str]:
    async with db.execute(
        "SELECT category, COUNT(*) c FROM rules GROUP BY category ORDER BY category"
    ) as cur:
        return [row["category"] for row in await cur.fetchall()]


async def list_rules_by_category(db: aiosqlite.Connection, category: str) -> list[aiosqlite.Row]:
    async with db.execute(
        "SELECT * FROM rules WHERE category = ? ORDER BY use_count DESC, id",
        (category,),
    ) as cur:
        return list(await cur.fetchall())


async def search_rules(db: aiosqlite.Connection, term: str, limit: int = 20) -> list[aiosqlite.Row]:
    like = f"%{term.strip()}%"
    async with db.execute(
        "SELECT * FROM rules WHERE text LIKE ? OR category LIKE ? "
        "ORDER BY use_count DESC, id LIMIT ?",
        (like, like, limit),
    ) as cur:
        return list(await cur.fetchall())


async def bump_rule_use(db: aiosqlite.Connection, rule_id: int) -> None:
    await db.execute("UPDATE rules SET use_count = use_count + 1 WHERE id = ?", (rule_id,))
    await db.commit()


async def list_all_rules(db: aiosqlite.Connection) -> list[aiosqlite.Row]:
    """All rules, grouped-friendly (category then favorites) — for the web menu."""
    async with db.execute(
        "SELECT * FROM rules ORDER BY category, is_favorite DESC, id"
    ) as cur:
        return list(await cur.fetchall())


# --- Fines -----------------------------------------------------------------
# Create/dispute/pay live here; the lifecycle policy (cooling window, sweep)
# lives in fines.py so this stays plain data-access.

async def insert_fine(
    db: aiosqlite.Connection,
    member_id: int,
    rule_id: Optional[int],
    amount: int,
    added_by: int,
    status: str,
    confirm_deadline: Optional[str],
    ts: Optional[str] = None,
) -> int:
    # ts is injectable so the caller can derive `ts` and `confirm_deadline` from
    # ONE clock read (BR-031: confirm_deadline == ts + COOLING_HOURS exactly).
    cur = await db.execute(
        "INSERT INTO fines (member_id, rule_id, amount, ts, added_by, status, "
        "confirm_deadline) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (member_id, rule_id, amount, ts or now_iso(), added_by, status, confirm_deadline),
    )
    await db.commit()
    return cur.lastrowid


async def get_fine(db: aiosqlite.Connection, fine_id: int) -> Optional[aiosqlite.Row]:
    if not _fits_i64(fine_id):
        return None
    async with db.execute("SELECT * FROM fines WHERE id = ?", (fine_id,)) as cur:
        return await cur.fetchone()


async def dispute_fine(db: aiosqlite.Connection, fine_id: int, reason: Optional[str] = None) -> None:
    await db.execute(
        "UPDATE fines SET status = 'disputed', dispute_reason = ? WHERE id = ?",
        (reason, fine_id),
    )
    await db.commit()


async def mark_fine_paid(db: aiosqlite.Connection, fine_id: int) -> None:
    await db.execute("UPDATE fines SET paid = 1 WHERE id = ?", (fine_id,))
    await db.commit()


async def recent_fines(db: aiosqlite.Connection, limit: int = 20) -> list[aiosqlite.Row]:
    async with db.execute(
        "SELECT f.*, m.name AS member_name, a.name AS accuser_name, r.text AS rule_text "
        "FROM fines f "
        "JOIN members m ON m.id = f.member_id "
        "JOIN members a ON a.id = f.added_by "
        "LEFT JOIN rules r ON r.id = f.rule_id "
        "ORDER BY f.ts DESC LIMIT ?",
        (limit,),
    ) as cur:
        return list(await cur.fetchall())


# --- Money calcs -----------------------------------------------------------

async def pot_total(db: aiosqlite.Connection) -> int:
    """The fine pot = sum of confirmed/upheld fines.

    (Month-end "apply pot to rent" is a v3 settle step; until then nothing is
    applied, so the pot is the full confirmed sum.)
    """
    placeholders = ",".join("?" * len(OWED_STATUSES))
    async with db.execute(
        f"SELECT COALESCE(SUM(amount), 0) FROM fines WHERE status IN ({placeholders})",
        OWED_STATUSES,
    ) as cur:
        (total,) = await cur.fetchone()
    return total


async def member_dues(db: aiosqlite.Connection, member_id: int) -> dict:
    """What one member owes: unpaid confirmed/upheld fines + unpaid bill shares."""
    placeholders = ",".join("?" * len(OWED_STATUSES))
    async with db.execute(
        f"SELECT COALESCE(SUM(amount), 0) FROM fines "
        f"WHERE member_id = ? AND paid = 0 AND status IN ({placeholders})",
        (member_id, *OWED_STATUSES),
    ) as cur:
        (fines_owed,) = await cur.fetchone()
    async with db.execute(
        "SELECT COALESCE(SUM(share_amount), 0) FROM bill_shares "
        "WHERE member_id = ? AND paid = 0",
        (member_id,),
    ) as cur:
        (bills_owed,) = await cur.fetchone()
    return {
        "fines": fines_owed,
        "bills": bills_owed,
        "total": fines_owed + bills_owed,
    }


async def all_dues(db: aiosqlite.Connection) -> list[dict]:
    """Dues per active member, biggest debtor first."""
    rows = []
    for m in await list_active_members(db):
        d = await member_dues(db, m["id"])
        rows.append({"member_id": m["id"], "name": m["name"], **d})
    return sorted(rows, key=lambda r: r["total"], reverse=True)


async def hall_of_shame(db: aiosqlite.Connection, limit: int = 10) -> list[dict]:
    """Most-fined active members (the fun guest-page leaderboard): count + total
    of their confirmed/upheld fines. Only those with at least one."""
    placeholders = ",".join("?" * len(OWED_STATUSES))
    async with db.execute(
        f"SELECT m.name, COUNT(f.id) AS fines, COALESCE(SUM(f.amount), 0) AS total "
        f"FROM members m JOIN fines f ON f.member_id = m.id "
        f"WHERE m.is_active = 1 AND f.status IN ({placeholders}) "
        f"GROUP BY m.id, m.name "
        f"ORDER BY total DESC, fines DESC LIMIT ?",
        (*OWED_STATUSES, limit),
    ) as cur:
        return [dict(row) for row in await cur.fetchall()]


async def owed_fine_count(db: aiosqlite.Connection) -> int:
    """How many fines make up the pot (confirmed/upheld) — for the /pot message."""
    placeholders = ",".join("?" * len(OWED_STATUSES))
    async with db.execute(
        f"SELECT COUNT(*) FROM fines WHERE status IN ({placeholders})", OWED_STATUSES
    ) as cur:
        (n,) = await cur.fetchone()
    return n


async def list_unpaid_owed_fines(
    db: aiosqlite.Connection, member_id: int
) -> list[aiosqlite.Row]:
    """A member's collectable, still-unpaid fines (for the /dues pay buttons)."""
    placeholders = ",".join("?" * len(OWED_STATUSES))
    async with db.execute(
        f"SELECT f.id, f.amount, r.text AS rule_text "
        f"FROM fines f LEFT JOIN rules r ON r.id = f.rule_id "
        f"WHERE f.member_id = ? AND f.paid = 0 AND f.status IN ({placeholders}) "
        f"ORDER BY f.ts",
        (member_id, *OWED_STATUSES),
    ) as cur:
        return list(await cur.fetchall())


async def list_unpaid_shares(
    db: aiosqlite.Connection, member_id: int
) -> list[aiosqlite.Row]:
    """A member's unpaid bill shares (for the /dues pay buttons)."""
    async with db.execute(
        "SELECT s.id, s.bill_id, s.share_amount, b.type, b.month "
        "FROM bill_shares s JOIN bills b ON b.id = s.bill_id "
        "WHERE s.member_id = ? AND s.paid = 0 "
        "ORDER BY b.month, b.type",
        (member_id,),
    ) as cur:
        return list(await cur.fetchall())


async def overturn_stats(db: aiosqlite.Connection) -> list[dict]:
    """Visible accuser-accountability stat (DESIGN Layer 3, read-only in v1).

    filed   = fines this member reported (added_by)
    upheld  = of those, still standing (confirmed/upheld)
    voided  = of those, thrown out (void/disputed)
    """
    async with db.execute(
        "SELECT a.id, a.name, "
        "  COUNT(f.id) AS filed, "
        "  SUM(CASE WHEN f.status IN ('confirmed','upheld') THEN 1 ELSE 0 END) AS upheld, "
        "  SUM(CASE WHEN f.status IN ('void','disputed') THEN 1 ELSE 0 END) AS overturned "
        "FROM members a LEFT JOIN fines f ON f.added_by = a.id "
        "WHERE a.is_active = 1 "
        "GROUP BY a.id, a.name "
        "ORDER BY overturned DESC, filed DESC"
    ) as cur:
        out = []
        for row in await cur.fetchall():
            filed = row["filed"] or 0
            overturned = row["overturned"] or 0
            rate = round(100 * overturned / filed) if filed else 0
            out.append(
                {
                    "name": row["name"],
                    "filed": filed,
                    "upheld": row["upheld"] or 0,
                    "overturned": overturned,
                    "overturn_rate": rate,
                }
            )
        return out


# --- Bills (with the load-bearing snapshot) --------------------------------

async def create_bill_with_shares(
    db: aiosqlite.Connection,
    bill_type: str,
    total: int,
    month: str,
    paid_by: Optional[int] = None,
) -> int:
    """Record a bill AND snapshot one bill_shares row per active tenant.

    THIS IS THE LOAD-BEARING BIT. Splits are frozen at creation time so adding
    a 5th tenant later never rewrites this month's split. Never compute
    `total ÷ count` live anywhere else. (Guests don't pay bills — tenants only.)

    The remainder from integer division is given to the first tenant so the
    shares always sum to exactly `total`.
    """
    tenants = await list_active_tenants(db)
    if not tenants:
        raise ValueError("Cannot create a bill with no active tenants to split it.")

    cur = await db.execute(
        "INSERT INTO bills (type, total, month, paid_by, ts) VALUES (?, ?, ?, ?, ?)",
        (bill_type, total, month, paid_by, now_iso()),
    )
    bill_id = cur.lastrowid

    base, remainder = divmod(total, len(tenants))
    for i, t in enumerate(tenants):
        share = base + (remainder if i == 0 else 0)
        await db.execute(
            "INSERT INTO bill_shares (bill_id, member_id, share_amount) VALUES (?, ?, ?)",
            (bill_id, t["id"], share),
        )
    await db.commit()
    return bill_id


async def mark_share_paid(db: aiosqlite.Connection, bill_id: int, member_id: int) -> None:
    await db.execute(
        "UPDATE bill_shares SET paid = 1 WHERE bill_id = ? AND member_id = ?",
        (bill_id, member_id),
    )
    await db.commit()


async def get_bill(db: aiosqlite.Connection, bill_id: int) -> Optional[aiosqlite.Row]:
    async with db.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)) as cur:
        return await cur.fetchone()


async def list_bill_shares(
    db: aiosqlite.Connection, bill_id: int
) -> list[aiosqlite.Row]:
    """Every snapshotted share for a bill, with member names (for the bill card)."""
    async with db.execute(
        "SELECT s.member_id, s.share_amount, s.paid, m.name "
        "FROM bill_shares s JOIN members m ON m.id = s.member_id "
        "WHERE s.bill_id = ? ORDER BY m.name",
        (bill_id,),
    ) as cur:
        return list(await cur.fetchall())
