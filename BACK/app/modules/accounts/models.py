import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, EntityMixin


class Workspace(EntityMixin, Base):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(200))
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    timezone: Mapped[str] = mapped_column(String(64), server_default="Europe/Moscow")
    currency: Mapped[str] = mapped_column(String(3), server_default="RUB")


class Store(EntityMixin, Base):
    __tablename__ = "stores"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_stores_workspace_id_id"),
        UniqueConstraint(
            "workspace_id",
            "marketplace",
            "external_seller_id",
            name="uq_stores_workspace_marketplace_seller",
        ),
        CheckConstraint("marketplace IN ('wildberries', 'ozon')", name="marketplace"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    marketplace: Mapped[str] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    external_seller_id: Mapped[str | None] = mapped_column(String(100))
    connection_status: Mapped[str] = mapped_column(String(32), server_default="not_connected")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkspaceInvite(EntityMixin, Base):
    """Team invitation. Only the token digest is stored; accepted via perk_accept_invite()."""

    __tablename__ = "workspace_invites"
    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'admin', 'manager', 'accountant', 'viewer')", name="role"
        ),
        CheckConstraint(
            "permissions IS NULL OR jsonb_typeof(permissions)='array'", name="permissions_array"
        ),
        CheckConstraint(
            "store_ids IS NULL OR jsonb_typeof(store_ids)='array'", name="stores_array"
        ),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(16))
    permissions: Mapped[list[str] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    store_ids: Mapped[list[str] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    invited_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class StoreCredential(EntityMixin, Base):
    __tablename__ = "store_credentials"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
        UniqueConstraint("store_id"),
    )
    workspace_id: Mapped[uuid.UUID]
    store_id: Mapped[uuid.UUID]
    ciphertext: Mapped[str] = mapped_column(Text)
    scopes: Mapped[str] = mapped_column(String(500))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
