"""auth: email OTP challenges + session/lockout columns on members

`otp_challenges` holds one emailed code per (purpose, address) attempt — digest only,
with expiry, attempt/resend counters and one-time-use stamps; signup challenges carry
the pending registration, verified reset challenges a digested reset token.

members gains:
  * email_verified_at — when the current email was proven by a code. Existing
    addresses stay NULL (unverified) — they still receive notifications and can be
    used for password reset; a reset or re-verification stamps them.
  * session_version — mirrored into the login cookie; bumping it revokes other
    sessions. Existing cookies carry no version and count as 0, so nobody is logged
    out by this migration.
  * failed_logins / locked_until — the login brute-force lockout.

Revision ID: a9c4e2f7d1b6
Revises: f8a2c4d6e1b3
Create Date: 2026-11-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a9c4e2f7d1b6"
down_revision: Union[str, None] = "f8a2c4d6e1b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "otp_challenges",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=True),
        sa.Column("code_hash", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("send_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("last_sent_at", sa.String(), nullable=False),
        sa.Column("expires_at", sa.String(), nullable=False),
        sa.Column("verified_at", sa.String(), nullable=True),
        sa.Column("consumed_at", sa.String(), nullable=True),
        sa.Column("reset_token_hash", sa.String(), nullable=True),
        sa.Column("reset_expires_at", sa.String(), nullable=True),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("password_hash", sa.String(), nullable=True),
        sa.Column("whatsapp", sa.String(), nullable=True),
        sa.Column("invite_token", sa.String(), nullable=True),
        sa.CheckConstraint(
            "purpose IN ('register', 'password_reset', 'change_email')",
            name=op.f("ck_otp_challenges_purpose_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["member_id"], ["members.id"], name=op.f("fk_otp_challenges_member_id_members")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_otp_challenges")),
    )
    op.create_index("idx_otp_purpose_email", "otp_challenges", ["purpose", "email"], unique=False)
    op.create_index("idx_otp_reset_token", "otp_challenges", ["reset_token_hash"], unique=False)
    op.create_index("idx_otp_expires", "otp_challenges", ["expires_at"], unique=False)

    with op.batch_alter_table("members", schema=None) as batch_op:
        batch_op.add_column(sa.Column("email_verified_at", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column("session_version", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("failed_logins", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("locked_until", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("members", schema=None) as batch_op:
        batch_op.drop_column("locked_until")
        batch_op.drop_column("failed_logins")
        batch_op.drop_column("session_version")
        batch_op.drop_column("email_verified_at")

    op.drop_index("idx_otp_expires", table_name="otp_challenges")
    op.drop_index("idx_otp_reset_token", table_name="otp_challenges")
    op.drop_index("idx_otp_purpose_email", table_name="otp_challenges")
    op.drop_table("otp_challenges")
