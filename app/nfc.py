"""NFC spots — the `/s/<spot>` contextual pages (DESIGN.md "NFC stickers").

A code-level config (data, like seed.py — not a table). Each spot maps to a
title, an emoji, and an optional rule-category PRE-FILTER: tapping the kitchen
sticker shows only kitchen rules in the report form (location = category filter).
`shame` flips the living-room "control room" into the Hall-of-Shame view.

The `category` values must match the seed rule categories.
"""

from __future__ import annotations

SPOTS: dict[str, dict] = {
    "front_door":  {"emoji": "🚪", "title": "Welcome to Hive", "category": None,       "shame": False},
    "fridge":      {"emoji": "🧊", "title": "Pay & the pot",       "category": None,       "shame": False},
    "kitchen":     {"emoji": "🚰", "title": "Kitchen",             "category": "kitchen",  "shame": False},
    "balcony":     {"emoji": "🚬", "title": "Balcony",             "category": "smoking",  "shame": False},
    "living_room": {"emoji": "📺", "title": "The control room",    "category": None,       "shame": True},
    "bathroom":    {"emoji": "🚽", "title": "Bathroom",            "category": "bathroom", "shame": False},
}
