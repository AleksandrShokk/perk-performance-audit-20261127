"""Neutral daily sales and native stock coverage, independent of WB record identifiers."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
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


class MarketplaceSalesDay(Base):
    __tablename__ = "marketplace_sales_days"
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


class MarketplaceStockCover(Base):
    __tablename__ = "marketplace_stock_cover"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    store_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OzonAnalyticsSync(Base):
    """Metadata-only outbox, reauthorized by workers before accessing seller data."""

    __tablename__ = "ozon_analytics_sync"
    __table_args__ = (
        Index("ix_ozon_analytics_due", "next_attempt_at"),
        ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
        CheckConstraint(
            "source IN ('sales','stock_cover','finance','traffic','supplies')", name="source"
        ),
        CheckConstraint("status IN ('pending','queued','running','ready','error')", name="status"),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    store_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(16), primary_key=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    run_id: Mapped[uuid.UUID | None]
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    records_processed: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    history_from: Mapped[date | None] = mapped_column(Date)
    cursor: Mapped[date | None] = mapped_column(Date)
    date_from: Mapped[date | None] = mapped_column(Date)
    date_to: Mapped[date | None] = mapped_column(Date)
    mode: Mapped[str] = mapped_column(String(16), default="history")
