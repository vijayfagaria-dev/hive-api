"""expenses: revamp categories — add rent/maintenance/cook, rename brokerage→broker, drop utilities

Rent is now a shared, fronted expense (category='rent', split by rent-share %), and the
granular utility/help buckets (water, electricity, gas, cleaner) collapse into a single
'maintenance'. Existing rows are remapped BEFORE the CHECK constraint is recreated, so no
row is ever left violating it.

Revision ID: b7c1d2e3f4a5
Revises: e5f6a7b8c9d0
Create Date: 2026-07-04
"""

from typing import Sequence, Union

from alembic import op

revision: str = "b7c1d2e3f4a5"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CK = "ck_expenses_expense_category_valid"
_NEW = "category IN ('rent','maintenance','internet','house_help','cook','groceries','broker','misc')"
_OLD = "category IN ('electricity','water','house_help','internet','gas','cleaner','groceries','brokerage','misc')"

_UTILITIES = "('water','electricity','gas','cleaner')"


def upgrade() -> None:
    # 1) remap existing data to the new vocabulary (both the expenses feed and templates)
    for tbl in ("expenses", "expense_templates"):
        op.execute(f"UPDATE {tbl} SET category='maintenance' WHERE category IN {_UTILITIES}")
        op.execute(f"UPDATE {tbl} SET category='broker' WHERE category='brokerage'")
    # 2) recreate the CHECK on the expenses table with the new allowed set
    with op.batch_alter_table("expenses", schema=None) as batch_op:
        batch_op.drop_constraint(op.f(_CK), type_="check")
        batch_op.create_check_constraint(op.f(_CK), _NEW)


def downgrade() -> None:
    # Best-effort reverse: the old granular utilities can't be recovered, so anything not
    # representable in the old vocabulary collapses to a valid old value ('misc').
    for tbl in ("expenses", "expense_templates"):
        op.execute(f"UPDATE {tbl} SET category='brokerage' WHERE category='broker'")
        op.execute(f"UPDATE {tbl} SET category='misc' WHERE category IN ('rent','maintenance','cook')")
    with op.batch_alter_table("expenses", schema=None) as batch_op:
        batch_op.drop_constraint(op.f(_CK), type_="check")
        batch_op.create_check_constraint(op.f(_CK), _OLD)
