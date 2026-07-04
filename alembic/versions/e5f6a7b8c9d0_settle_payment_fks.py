"""settle<->payment foreign keys: SettleTxn.payment_id + Payment.settle_run_id

Turns the two Integer soft-links into real FKs so a settle transfer and the payment that
cleared it can't dangle. Data is already consistent (both are only ever set to real rows),
so this is a pure integrity tightening. `payments` is recreated first (it references
settle_runs); `settle_txns` second (it references the freshly-recreated payments).

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-04 13:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.create_foreign_key(
            batch_op.f('fk_payments_settle_run_id_settle_runs'), 'settle_runs', ['settle_run_id'], ['id']
        )
    with op.batch_alter_table('settle_txns', schema=None) as batch_op:
        batch_op.create_foreign_key(
            batch_op.f('fk_settle_txns_payment_id_payments'), 'payments', ['payment_id'], ['id']
        )


def downgrade() -> None:
    with op.batch_alter_table('settle_txns', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_settle_txns_payment_id_payments'), type_='foreignkey')
    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_payments_settle_run_id_settle_runs'), type_='foreignkey')
