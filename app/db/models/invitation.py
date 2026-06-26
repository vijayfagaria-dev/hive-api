"""Invitation ORM model — a pending invite to join the household at a given role.

A tenant mints a single-use, expiring token (a shareable link); the invitee
redeems it during registration and joins at the invited role instead of the
default guest. The row itself is the invite's audit record.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.enums import InvitationStatus
from app.domain.time import now_iso


class Invitation(Base):
    __tablename__ = "invitations"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String, nullable=False)        # url-safe, single-use
    role: Mapped[str] = mapped_column(String, nullable=False)         # role granted on accept
    name: Mapped[Optional[str]] = mapped_column(String)              # suggested display name
    email: Mapped[Optional[str]] = mapped_column(String)            # optional, advisory
    invited_by: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default=InvitationStatus.PENDING)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_iso)
    expires_at: Mapped[str] = mapped_column(String, nullable=False)
    accepted_by: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"))
    accepted_at: Mapped[Optional[str]] = mapped_column(String)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'accepted', 'revoked', 'expired')", name="status_valid"
        ),
        CheckConstraint("role IN ('tenant', 'guest')", name="role_valid"),
        Index("idx_invitations_token", "token", unique=True),
        Index("idx_invitations_status", "status"),
        Index("idx_invitations_inviter", "invited_by"),
    )
