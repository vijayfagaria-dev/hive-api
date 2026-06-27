"""The flat's house rules — loaded once on first boot when `rules` is empty.

Each rule has a severity LEVEL 1–5; the fine is fixed per level (L1=₹100 … L5=₹500).
Kept as data here (not DDL) so it's easy to amend. `python -m app.admin reset-rules`
applies this set to an already-seeded DB (deactivates anything not in this list).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Rule

# Severity level -> fine amount (₹).
LEVEL_FINES: dict[int, int] = {1: 100, 2: 200, 3: 300, 4: 400, 5: 500}

# (category, text, level, applies_to). Fine is derived from the level.
STARTER_RULES: list[tuple[str, str, int, str]] = [
    ("kitchen", "Clear all food from plates and containers before putting them in the sink.", 3, "both"),
    ("smoking", "Keep smoking outside — only use the balcony for smoking.", 5, "tenant"),
    ("common", "Remove empty water bottles from common areas and rooms promptly.", 2, "both"),
    ("common", "Turn off the AC and lights if leaving the room for more than 15 minutes.", 4, "both"),
    ("common", "Keep room doors closed while the AC is running to save energy.", 1, "both"),
    ("bills", "Ensure rent is paid on or before the agreed due date.", 1, "tenant"),
    ("general", "Wear only indoor slippers or walk barefoot inside the flat.", 3, "both"),
    ("kitchen", "Bring all used utensils back to the kitchen — don't leave them in rooms overnight.", 3, "both"),
    ("common", "Keep laundry neatly in laundry bags instead of leaving it scattered.", 1, "tenant"),
    ("common", "Store shoes neatly in the shoe rack at all times.", 1, "both"),
    ("common", "Return dining chairs to the dining area immediately after using them on the balcony.", 3, "both"),
    ("smoking", "Dispose of cigarette butts properly in the designated bins.", 3, "both"),
    ("common", "Keep common spaces clear by storing personal belongings in your room.", 3, "both"),
    ("general", "Always return home and vehicle keys to their designated spot after use.", 2, "both"),
    ("kitchen", "Put shared items (like snacks, salt, and pepper) back in their proper place after use.", 4, "both"),
]


def make_rule(category: str, text: str, level: int, applies_to: str) -> Rule:
    """Build a Rule from a (level-driven) definition: fine + severity flow from the level."""
    return Rule(
        category=category,
        text=text,
        level=level,
        applies_to=applies_to,
        fine_amount=LEVEL_FINES[level],
        severity_tier="high" if level >= 3 else "low",
        is_favorite=level >= 4,  # surface the costly ones as favorites
    )


async def seed_if_empty(session: AsyncSession) -> int:
    """Insert the house rules only when the table is empty. Returns count added."""
    existing = await session.scalar(select(func.count()).select_from(Rule))
    if existing:
        return 0
    session.add_all(make_rule(*r) for r in STARTER_RULES)
    return len(STARTER_RULES)


async def converge_rules(session: AsyncSession) -> tuple[int, int]:
    """Make the *active* rule set exactly STARTER_RULES (matched by text): add anything
    missing, deactivate anything extra. Idempotent + FK-safe — extras are soft-deleted
    (is_active=False), never row-removed, so fines/history that reference them survive.
    Returns (added, deactivated)."""
    desired = {text: (cat, text, lvl, app) for (cat, text, lvl, app) in STARTER_RULES}
    existing = list(await session.scalars(select(Rule)))
    active_desired: set[str] = set()
    deactivated = 0
    for rule in existing:
        if rule.is_active and rule.text not in desired:
            rule.is_active = False
            deactivated += 1
        elif rule.is_active and rule.text in desired:
            active_desired.add(rule.text)
    added = 0
    for text, defn in desired.items():
        if text not in active_desired:
            session.add(make_rule(*defn))
            added += 1
    return added, deactivated
