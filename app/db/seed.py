"""Starter rule set — loaded once on first boot when `rules` is empty.

A PLACEHOLDER (DESIGN.md → "Still open"): paste the flat's real rules to replace
it. Kept as data here (not DDL) so it's easy to swap out.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Rule

# (category, text, fine_amount, is_favorite)
STARTER_RULES: list[tuple[str, str, int, bool]] = [
    ("kitchen",  "Left dirty dishes in the sink",                50,  True),
    ("kitchen",  "Didn't refill the water filter",               20,  True),
    ("kitchen",  "Ate someone else's labelled food",             50,  False),
    ("kitchen",  "Left the stove/gas on after cooking",          100, False),
    ("bathroom", "Left the bathroom a mess",                     50,  True),
    ("bathroom", "Used the last of the toilet paper, no refill", 30,  False),
    ("common",   "Left shoes/clothes in the common area",        20,  True),
    ("common",   "Didn't take the trash out on your day",        50,  False),
    ("common",   "Left lights/AC on in an empty room",           30,  False),
    ("noise",    "Loud music/calls after midnight",              50,  True),
    ("noise",    "Alarm went off for ages while you were out",   20,  False),
    ("guests",   "Unannounced guest stayed over",                50,  False),
    ("guests",   "Guest broke a house rule (host pays)",         50,  False),
    ("bills",    "Paid your share of a bill late",               50,  True),
    ("smoking",  "Smoked indoors instead of the balcony",        100, False),
    ("general",  "Frivolous / joke fine on someone else",        50,  False),
]


async def seed_if_empty(session: AsyncSession) -> int:
    """Insert the starter rules only when the table is empty. Returns count added."""
    existing = await session.scalar(select(func.count()).select_from(Rule))
    if existing:
        return 0
    session.add_all(
        Rule(category=c, text=t, fine_amount=a, is_favorite=fav)
        for c, t, a, fav in STARTER_RULES
    )
    return len(STARTER_RULES)
