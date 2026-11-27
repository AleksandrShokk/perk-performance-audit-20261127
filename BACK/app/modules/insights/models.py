import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, ForeignKeyConstraint, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class InsightSnapshot(Base):
    """Precomputed encrypted report. Served instantly; refreshed in the background on change."""

    __tablename__ = "insight_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    store_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    params_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    revision: Mapped[str] = mapped_column(String(64))
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ciphertext: Mapped[str] = mapped_column(Text)


class StoreEvent(Base):
    """Journal shown on charts: price changes, ad launches, supplies, promotions."""

    __tablename__ = "store_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    store_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    day: Mapped[date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(32))
    nm_id: Mapped[str | None] = mapped_column(String(32))
    ciphertext: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StoreGoal(Base):
    """Monthly target for plan/fact. Amounts are decimal strings, encrypted with the metric."""

    __tablename__ = "store_goals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    store_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    month: Mapped[date] = mapped_column(Date, primary_key=True)
    metric: Mapped[str] = mapped_column(String(16), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
