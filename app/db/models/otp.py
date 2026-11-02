"""OtpChallenge ORM model — one emailed 6-digit code and everything that guards it.

One row per (purpose, address) attempt: the code is stored only as a keyed digest,
with its expiry, wrong-guess counter, resend bookkeeping, and `consumed_at` for
one-time use. A signup challenge also carries the pending registration (the member
row is only created once the email is proven); a password-reset challenge, once
verified, carries a short-lived single-use reset token (also digested).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.time import now_iso


class OtpChallenge(Base):
    __tablename__ = "otp_challenges"

    id: Mapped[int] = mapped_column(primary_key=True)
    purpose: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False)        # normalized (lower-case)
    member_id: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"))  # reset / email change
    code_hash: Mapped[str] = mapped_column(String, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    send_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_iso)
    last_sent_at: Mapped[str] = mapped_column(String, nullable=False, default=now_iso)
    expires_at: Mapped[str] = mapped_column(String, nullable=False)
    verified_at: Mapped[Optional[str]] = mapped_column(String)
    consumed_at: Mapped[Optional[str]] = mapped_column(String)
    # Password reset: issued on a verified code, redeemed once for the new password.
    reset_token_hash: Mapped[Optional[str]] = mapped_column(String)
    reset_expires_at: Mapped[Optional[str]] = mapped_column(String)
    # Signup: the registration waiting on this code (password already bcrypt-hashed).
    username: Mapped[Optional[str]] = mapped_column(String)
    password_hash: Mapped[Optional[str]] = mapped_column(String)
    whatsapp: Mapped[Optional[str]] = mapped_column(String)
    invite_token: Mapped[Optional[str]] = mapped_column(String)

    __table_args__ = (
        CheckConstraint(
            "purpose IN ('register', 'password_reset', 'change_email')", name="purpose_valid"
        ),
        Index("idx_otp_purpose_email", "purpose", "email"),
        Index("idx_otp_reset_token", "reset_token_hash"),
        Index("idx_otp_expires", "expires_at"),
    )
