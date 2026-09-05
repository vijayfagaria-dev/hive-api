"""settle_txns: track partial payments via paid_amount

A proposed transfer used to be all-or-nothing: marking it paid wrote a Payment for the
full amount and closed the row. `paid_amount` accumulates what has actually been paid so
a debtor can pay part now and the rest later — the row stays 'proposed' with the
remainder visible until it's covered. `amount` stays the untouched snapshot of what the
simplifier proposed.

Backfill: rows already 'paid' are fully paid by definition, so paid_amount = amount.
'proposed' and 'cancelled' rows keep the 0 default.

Revision ID: f8a2c4d6e1b3
Revises: b7c1d2e3f4a5
Create Date: 2026-09-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f8a2c4d6e1b3"
down_revision: Union[str, None] = "b7c1d2e3f4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CK = "ck_settle_txns_settle_txn_paid_within_amount"


def upgrade() -> None:
    with op.batch_alter_table("settle_txns", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("paid_amount", sa.Integer(), nullable=False, server_default="0")
        )
    # Existing settled rows were paid in full — reflect that before the CHECK goes on.
    op.execute("UPDATE settle_txns SET paid_amount = amount WHERE status = 'paid'")
    with op.batch_alter_table("settle_txns", schema=None) as batch_op:
        batch_op.create_check_constraint(
            op.f(_CK), "paid_amount >= 0 AND paid_amount <= amount"
        )


def downgrade() -> None:
    with op.batch_alter_table("settle_txns", schema=None) as batch_op:
        batch_op.drop_constraint(op.f(_CK), type_="check")
        batch_op.drop_column("paid_amount")
