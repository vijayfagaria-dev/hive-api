"""Starter rule set — loaded once on first boot when `rules` is empty.

This is a PLACEHOLDER. Paste the flat's real rules + fines list to replace it
(DESIGN.md → "Still open"). Categories loosely track the NFC spots so a kitchen
tap can pre-filter to kitchen rules later (v2).

Kept here (not in schema.sql) so it's data, not DDL, and easy to swap out.
"""

from __future__ import annotations

import aiosqlite

from . import queries

# (category, text, fine_amount, is_favorite)
# Favorites are the ~handful that cause most fines — they become quick buttons.
STARTER_RULES: list[tuple[str, str, int, bool]] = [
    ("kitchen",  "Left dirty dishes in the sink",            50,  True),
    ("kitchen",  "Didn't refill the water filter",           20,  True),
    ("kitchen",  "Ate someone else's labelled food",         50,  False),
    ("kitchen",  "Left the stove/gas on after cooking",      100, False),
    ("bathroom", "Left the bathroom a mess",                 50,  True),
    ("bathroom", "Used the last of the toilet paper, no refill", 30, False),
    ("common",   "Left shoes/clothes in the common area",    20,  True),
    ("common",   "Didn't take the trash out on your day",    50,  False),
    ("common",   "Left lights/AC on in an empty room",       30,  False),
    ("noise",    "Loud music/calls after midnight",          50,  True),
    ("noise",    "Alarm went off for ages while you were out", 20, False),
    ("guests",   "Unannounced guest stayed over",            50,  False),
    ("guests",   "Guest broke a house rule (host pays)",     50,  False),
    ("bills",    "Paid your share of a bill late",           50,  True),
    ("smoking",  "Smoked indoors instead of the balcony",    100, False),
    ("general",  "Frivolous / joke fine on someone else",    50,  False),
]


async def seed_rules(db: aiosqlite.Connection) -> int:
    """Insert the starter rules. Returns how many were added."""
    for category, text, amount, favorite in STARTER_RULES:
        await queries.add_rule(
            db,
            category=category,
            text=text,
            fine_amount=amount,
            is_favorite=favorite,
        )
    return len(STARTER_RULES)
