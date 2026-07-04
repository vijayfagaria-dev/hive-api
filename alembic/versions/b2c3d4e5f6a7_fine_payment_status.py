"""fines payment lifecycle: payment_status + pay_by + paid_at (Bug 2)

Adds an explicit payment axis so acceptance (registration) no longer looks settled: a
registered fine is OWED with a pay-by countdown, and only marking-paid settles it. The
legacy `paid` boolean is kept in sync as a derived alias. Backfill:
  - paid=1                                   -> payment_status='settled', paid_at=resolved_at/ts
  - paid=0 AND status IN (confirmed,upheld)  -> payment_status='owed'   (no legacy countdown)
  - everything else                          -> payment_status='not_owed'

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-04 11:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('fines', schema=None) as batch_op:
        batch_op.add_column(sa.Column('payment_status', sa.String(), nullable=False, server_default='not_owed'))
        batch_op.add_column(sa.Column('pay_by', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('paid_at', sa.String(), nullable=True))
        batch_op.create_index('idx_fines_payment', ['payment_status', 'pay_by'], unique=False)

    # Backfill the payment axis from the legacy status/paid state.
    op.execute(
        "UPDATE fines SET payment_status='settled', paid_at=COALESCE(resolved_at, ts) "
        "WHERE paid=1"
    )
    op.execute(
        "UPDATE fines SET payment_status='owed' "
        "WHERE paid=0 AND status IN ('confirmed','upheld')"
    )

    # Drop the server_default so new rows use the app-side default.
    with op.batch_alter_table('fines', schema=None) as batch_op:
        batch_op.alter_column('payment_status', server_default=None)


def downgrade() -> None:
    with op.batch_alter_table('fines', schema=None) as batch_op:
        batch_op.drop_index('idx_fines_payment')
        batch_op.drop_column('paid_at')
        batch_op.drop_column('pay_by')
        batch_op.drop_column('payment_status')
