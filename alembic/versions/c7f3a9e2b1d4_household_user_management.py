"""household user management — invitations + member audit events

Revision ID: c7f3a9e2b1d4
Revises: 5b9e97c3965a
Create Date: 2026-06-27 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c7f3a9e2b1d4'
down_revision: Union[str, None] = '5b9e97c3965a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'invitations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('email', sa.String(), nullable=True),
        sa.Column('invited_by', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('expires_at', sa.String(), nullable=False),
        sa.Column('accepted_by', sa.Integer(), nullable=True),
        sa.Column('accepted_at', sa.String(), nullable=True),
        sa.CheckConstraint("role IN ('tenant', 'guest')", name=op.f('ck_invitations_role_valid')),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'revoked', 'expired')",
            name=op.f('ck_invitations_status_valid'),
        ),
        sa.ForeignKeyConstraint(['accepted_by'], ['members.id'], name=op.f('fk_invitations_accepted_by_members')),
        sa.ForeignKeyConstraint(['invited_by'], ['members.id'], name=op.f('fk_invitations_invited_by_members')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_invitations')),
    )
    with op.batch_alter_table('invitations', schema=None) as batch_op:
        batch_op.create_index('idx_invitations_token', ['token'], unique=True)
        batch_op.create_index('idx_invitations_status', ['status'], unique=False)
        batch_op.create_index('idx_invitations_inviter', ['invited_by'], unique=False)

    op.create_table(
        'member_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('member_id', sa.Integer(), nullable=False),
        sa.Column('type', sa.String(), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('detail', sa.String(), nullable=True),
        sa.Column('old_value', sa.String(), nullable=True),
        sa.Column('new_value', sa.String(), nullable=True),
        sa.Column('ts', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['actor_id'], ['members.id'], name=op.f('fk_member_events_actor_id_members')),
        sa.ForeignKeyConstraint(['member_id'], ['members.id'], name=op.f('fk_member_events_member_id_members')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_member_events')),
    )
    with op.batch_alter_table('member_events', schema=None) as batch_op:
        batch_op.create_index('idx_mevents_member', ['member_id', 'ts'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('member_events', schema=None) as batch_op:
        batch_op.drop_index('idx_mevents_member')
    op.drop_table('member_events')

    with op.batch_alter_table('invitations', schema=None) as batch_op:
        batch_op.drop_index('idx_invitations_inviter')
        batch_op.drop_index('idx_invitations_status')
        batch_op.drop_index('idx_invitations_token')
    op.drop_table('invitations')
