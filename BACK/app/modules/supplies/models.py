"""Seller-defined packaging, isolated by company, cabinet and native product."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SupplyPlan(Base):
    __tablename__ = "supply_plans"
    __table_args__ = (
        Index("ix_supply_plans_workspace_updated", "workspace_id", "updated_at", "id"),
        ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
        CheckConstraint("revision >= 1", name="plan_revision"),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    store_id: Mapped[uuid.UUID] = mapped_column(index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    ciphertext: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SupplyPackaging(Base):
    __tablename__ = "supply_packaging"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
        CheckConstraint("box_multiple BETWEEN 1 AND 10000", name="box_multiple"),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    store_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    product_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    box_multiple: Mapped[int] = mapped_column(Integer)
    updated_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
