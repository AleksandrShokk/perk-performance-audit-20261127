"""Encrypted WB regional facts and a metadata-only background outbox."""

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, ForeignKeyConstraint, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SupplyDestinationSnapshot(Base):
    __tablename__ = "supply_destination_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    store_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    product_key: Mapped[str] = mapped_column(String(24), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SupplyDestinationSync(Base):
    __tablename__ = "supply_destination_sync"
    __table_args__ = (
        Index("ix_supply_destination_due", "next_attempt_at"),
        ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    store_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    product_key: Mapped[str] = mapped_column(String(24), primary_key=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    run_id: Mapped[uuid.UUID | None]
    date_from: Mapped[date] = mapped_column(Date)
    date_to: Mapped[date] = mapped_column(Date)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
