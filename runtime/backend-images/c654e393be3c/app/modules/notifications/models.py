import uuid
from datetime import date, datetime

from app.db.base import Base, EntityMixin
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class NotificationSettings(Base):
    __tablename__ = "notification_settings"
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    telegram_chat_ciphertext: Mapped[str | None] = mapped_column(Text)
    telegram_linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    digest_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    digest_hour: Mapped[int] = mapped_column(Integer, server_default=text("9"))
    alerts_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    telegram_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    push_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    last_digest_on: Mapped[date | None] = mapped_column(Date)
    categories: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    timezone: Mapped[str] = mapped_column(
        String(64), default="Europe/Moscow", server_default="Europe/Moscow"
    )
    digest_mode: Mapped[str] = mapped_column(
        String(16), default="morning", server_default="morning"
    )
    quiet_start: Mapped[int] = mapped_column(Integer, default=22, server_default="22")
    quiet_end: Mapped[int] = mapped_column(Integer, default=9, server_default="9")
    show_details: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class Notification(EntityMixin, Base):
    """In-app feed item. Title/body/data are encrypted; the dedupe key prevents repeats."""

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "dedupe_key"),
        Index("ix_notifications_created_at", "created_at"),
        Index("ix_notifications_active_incident", "user_id", "incident_key", "resolved_at"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    store_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(16))
    dedupe_key: Mapped[str] = mapped_column(String(64))
    ciphertext: Mapped[str] = mapped_column(Text)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    incident_key: Mapped[str | None] = mapped_column(String(64))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_store_ids: Mapped[list] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    required_permissions: Mapped[list] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    delivery_state: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )


class PushDevice(EntityMixin, Base):
    __tablename__ = "push_devices"
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    token_ciphertext: Mapped[str] = mapped_column(Text)
    platform: Mapped[str] = mapped_column(String(16))
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="CASCADE")
    )
    session_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
