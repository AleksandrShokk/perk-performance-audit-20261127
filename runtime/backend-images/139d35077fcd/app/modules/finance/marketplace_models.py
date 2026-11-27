"""Encrypted provider-neutral finance days and analytic-only buyer price facts."""

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, ForeignKeyConstraint, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MarketplaceFinanceDay(Base):
    __tablename__ = "marketplace_finance_days"
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


class MarketplaceRealization(Base):
    """Only the customer's unit price, never commissions, costs, names or addresses."""

    __tablename__ = "marketplace_realizations"
    __table_args__ = (
        Index("ix_marketplace_realizations_posting", "workspace_id", "store_id", "posting_key"),
        ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    store_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    posting_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    sku: Mapped[str] = mapped_column(String(32), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)


class MarketplaceVariantCost(Base):
    __tablename__ = "marketplace_variant_costs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    store_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    variant_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    effective_from: Mapped[date] = mapped_column(Date, primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
