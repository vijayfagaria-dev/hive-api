"""notification_outbox — durable queue for out-of-band notification delivery

Moves push/email/WhatsApp sends out of the request transaction (a dispatcher drains
this table in the background), fixing the availability hazard where a slow send held
the SQLite write lock.

Revision ID: a1b2c3d4e5f6
Revises: 9d3a48551874
Create Date: 2026-07-04 11:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '9d3a48551874'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'notification_outbox',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('member_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('body', sa.String(), nullable=True),
        sa.Column('url', sa.String(), nullable=True),
        sa.Column('tag', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('next_attempt_at', sa.String(), nullable=False),
        sa.Column('last_error', sa.String(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('sent_at', sa.String(), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'sent', 'failed')", name=op.f('outbox_status_valid')),
        sa.ForeignKeyConstraint(['member_id'], ['members.id'], name=op.f('fk_notification_outbox_member_id_members')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_notification_outbox')),
    )
    with op.batch_alter_table('notification_outbox', schema=None) as batch_op:
        batch_op.create_index('idx_outbox_pending', ['status', 'next_attempt_at'], unique=False)

    # Drop the server_defaults so new rows use the app-side defaults.
    with op.batch_alter_table('notification_outbox', schema=None) as batch_op:
        batch_op.alter_column('status', server_default=None)
        batch_op.alter_column('attempts', server_default=None)


def downgrade() -> None:
    with op.batch_alter_table('notification_outbox', schema=None) as batch_op:
        batch_op.drop_index('idx_outbox_pending')
    op.drop_table('notification_outbox')
