"""devices — provider-agnostic push targets (Web Push / FCM / APNS) for Bug 3

Gives native (FCM/APNS) tokens a home alongside Web Push. New registrations write here;
the Web Push channel reads both this and the legacy push_subscriptions table.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-04 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'devices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('member_id', sa.Integer(), nullable=False),
        sa.Column('platform', sa.String(), nullable=False, server_default='web'),
        sa.Column('provider', sa.String(), nullable=False, server_default='webpush'),
        sa.Column('token', sa.String(), nullable=False),
        sa.Column('p256dh', sa.String(), nullable=True),
        sa.Column('auth', sa.String(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.text('1')),
        sa.Column('last_seen', sa.String(), nullable=False),
        sa.CheckConstraint("provider IN ('webpush', 'fcm', 'apns')", name=op.f('device_provider_valid')),
        sa.CheckConstraint("platform IN ('web', 'android', 'ios')", name=op.f('device_platform_valid')),
        sa.ForeignKeyConstraint(['member_id'], ['members.id'], name=op.f('fk_devices_member_id_members')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_devices')),
        sa.UniqueConstraint('token', name=op.f('uq_devices_token')),
    )
    with op.batch_alter_table('devices', schema=None) as batch_op:
        batch_op.create_index('idx_devices_member_provider', ['member_id', 'provider'], unique=False)

    # Drop server_defaults so new rows use the app-side defaults.
    with op.batch_alter_table('devices', schema=None) as batch_op:
        batch_op.alter_column('platform', server_default=None)
        batch_op.alter_column('provider', server_default=None)
        batch_op.alter_column('active', server_default=None)


def downgrade() -> None:
    with op.batch_alter_table('devices', schema=None) as batch_op:
        batch_op.drop_index('idx_devices_member_provider')
    op.drop_table('devices')
