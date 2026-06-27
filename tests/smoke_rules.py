"""House-rules seed smoke test — the 15 rules, level→fine, and convergence.

    .venv/bin/python3 tests/smoke_rules.py
"""

import asyncio
import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_PATH"] = os.path.join(tempfile.gettempdir(), f"hive_rules_{uuid.uuid4().hex}.db")

from app.db.seed import LEVEL_FINES, STARTER_RULES, converge_rules, seed_if_empty  # noqa: E402
from app.db.session import create_all, dispose, session_scope  # noqa: E402
from app.repositories import rules as rules_repo  # noqa: E402
from app.schemas.rules import rule_out  # noqa: E402


async def main():
    await create_all()
    try:
        async with session_scope() as s:
            added = await seed_if_empty(s)
        assert added == 15, added

        async with session_scope() as s:
            rules = await rules_repo.list_all(s)
        assert len(rules) == 15

        # every rule: fine is exactly level*100, level 1-5, applies_to valid, severity derived
        for r in rules:
            assert r.level in (1, 2, 3, 4, 5), r.level
            assert r.fine_amount == LEVEL_FINES[r.level] == r.level * 100
            assert r.applies_to in ("both", "tenant")
            assert r.severity_tier == ("high" if r.level >= 3 else "low")
        print("ok 15 rules seeded; fine == level*100; severity derived; applies_to valid")

        # spot-check the level extremes from the CSV
        smoke = next(r for r in rules if r.text.startswith("Keep smoking"))
        assert smoke.level == 5 and smoke.fine_amount == 500 and smoke.applies_to == "tenant" and smoke.category == "smoking"
        rent = next(r for r in rules if r.text.startswith("Ensure rent"))
        assert rent.level == 1 and rent.fine_amount == 100 and rent.applies_to == "tenant" and rent.category == "bills"
        print("ok spot-check: smoking=L5/₹500/tenant, rent=L1/₹100/tenant")

        # rule_out exposes the new fields
        out = rule_out(rules[0])
        assert out["level"] in (1, 2, 3, 4, 5) and out["appliesTo"] in ("both", "tenant")
        assert out["amount"] == out["level"] * 100
        print("ok rule_out exposes level + appliesTo")

        # re-seeding a non-empty table is a no-op
        async with session_scope() as s:
            assert await seed_if_empty(s) == 0

        # convergence: a stray rule gets deactivated, the set stays exactly 15
        async with session_scope() as s:
            await rules_repo.add(s, category="general", text="STRAY RULE", fine_amount=10)
        async with session_scope() as s:
            added2, deactivated2 = await converge_rules(s)
        assert added2 == 0 and deactivated2 == 1
        async with session_scope() as s:
            active = await rules_repo.list_all(s)
        assert len(active) == 15 and all(r.text != "STRAY RULE" for r in active)
        # idempotent: a second converge changes nothing
        async with session_scope() as s:
            assert await converge_rules(s) == (0, 0)
        print("ok converge_rules: deactivates strays, idempotent, stays at 15")

        print("\nRULES SMOKE: ALL CHECKS PASSED")
    finally:
        await dispose()


if __name__ == "__main__":
    asyncio.run(main())
