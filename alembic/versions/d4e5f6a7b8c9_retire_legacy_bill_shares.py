"""retire legacy bill_shares (bills superseded by expenses)

Bills were retired from the money net — recurring costs are expenses now, and the single
balance authority (services/balances.py) no longer reads bill_shares. Per the product
owner (no live bill_shares in production), this clears any legacy share rows so a stale
bill can't linger in a computed balance. The fine pot ("the jar") lives in `fines` /
`settlements` and is NOT touched. Bills/bill_events rows are left as historical audit.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-04 12:30:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No-op in production (no live shares). Clears any legacy rows so they can't surface
    # in a balance. Irreversible (data), hence no downgrade restore.
    op.execute("DELETE FROM bill_shares")


def downgrade() -> None:
    pass
