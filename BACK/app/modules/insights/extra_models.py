"""Encrypted provider snapshots; report permissions are independent of import ownership."""

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKeyConstraint, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MarketplaceTrafficDay(Base):
    __tablename__ = "marketplace_traffic_days"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    store_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MarketplaceSupplySnapshot(Base):
    __tablename__ = "marketplace_supply_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    store_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
