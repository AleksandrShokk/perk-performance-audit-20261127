import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProductMatch(Base):
    __tablename__ = "catalog_product_matches"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "left_store_id"],
            ["stores.workspace_id", "stores.id"],
            name="fk_catalog_matches_left_store",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "right_store_id"],
            ["stores.workspace_id", "stores.id"],
            name="fk_catalog_matches_right_store",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "workspace_id",
            "left_store_id",
            "left_variant_id",
            "right_store_id",
            name="uq_catalog_match_left",
        ),
        UniqueConstraint(
            "workspace_id",
            "right_store_id",
            "right_variant_id",
            "left_store_id",
            name="uq_catalog_match_right",
        ),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    left_store_id: Mapped[uuid.UUID]
    right_store_id: Mapped[uuid.UUID]
    left_variant_id: Mapped[uuid.UUID]
    right_variant_id: Mapped[uuid.UUID]
    ciphertext: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CatalogImportPreview(Base):
    __tablename__ = "catalog_import_previews"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "store_id"],
            ["stores.workspace_id", "stores.id"],
            ondelete="CASCADE",
        ),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID]
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(20))
    ciphertext: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
