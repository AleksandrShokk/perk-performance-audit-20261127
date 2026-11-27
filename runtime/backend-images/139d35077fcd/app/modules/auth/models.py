import uuid
from datetime import datetime

from app.db.base import Base, EntityMixin
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class User(EntityMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("phone_channel IN ('telegram', 'sms')", name="phone_channel"),
    )
    email: Mapped[str] = mapped_column(String(320), unique=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    phone: Mapped[str | None] = mapped_column(String(16), unique=True)
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    phone_channel: Mapped[str | None] = mapped_column(String(16))
    totp_ciphertext: Mapped[str | None] = mapped_column(Text)
    totp_pending_ciphertext: Mapped[str | None] = mapped_column(Text)
    totp_pending_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    totp_last_step: Mapped[int | None]

    @property
    def has_strong_factor(self) -> bool:
        # Email is a fallback only: a compromised mailbox must not unlock a protected account.
        return bool(self.phone_verified_at or self.totp_ciphertext)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'admin', 'manager', 'accountant', 'viewer')", name="role"
        ),
        CheckConstraint(
            "permissions IS NULL OR jsonb_typeof(permissions)='array'",
            name="permissions_array",
        ),
        CheckConstraint(
            "store_ids IS NULL OR jsonb_typeof(store_ids)='array'", name="stores_array"
        ),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(16))
    permissions: Mapped[list[str] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    store_ids: Mapped[list[str] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)


class AuthSession(EntityMixin, Base):
    __tablename__ = "auth_sessions"
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    client: Mapped[str] = mapped_column(String(16))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    mfa_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    step_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    strong_step_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    csrf_digest: Mapped[str] = mapped_column(String(64))


class OtpChallenge(EntityMixin, Base):
    """One-time code. Only digests are stored; registration data is encrypted until verified."""

    __tablename__ = "otp_challenges"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('register', 'login', 'step_up', 'phone_verify', "
            "'phone_change', 'password_reset')",
            name="purpose",
        ),
        CheckConstraint("channel IN ('email', 'telegram', 'sms')", name="channel"),
        CheckConstraint("attempts >= 0 AND sent_count >= 1", name="counters"),
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[str] = mapped_column(String(32))
    channel: Mapped[str] = mapped_column(String(16))
    destination_digest: Mapped[str] = mapped_column(String(64), index=True)
    code_digest: Mapped[str] = mapped_column(String(64))
    payload_ciphertext: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    sent_count: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    last_sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AccessToken(EntityMixin, Base):
    __tablename__ = "access_tokens"
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="CASCADE"), index=True
    )
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class RefreshToken(EntityMixin, Base):
    __tablename__ = "refresh_tokens"
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="CASCADE"), index=True
    )
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RecoveryCode(EntityMixin, Base):
    __tablename__ = "recovery_codes"
    __table_args__ = (UniqueConstraint("user_id", "code_digest"),)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    code_digest: Mapped[str] = mapped_column(String(64))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
