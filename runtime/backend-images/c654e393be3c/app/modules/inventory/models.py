import uuid
from datetime import date, datetime

from sqlalchemy import DateTime, ForeignKeyConstraint, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class InventorySnapshot(Base):
    """One encrypted row per SKU and Moscow day; the latest stock import of the day wins."""

    __tablename__ = "inventory_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    store_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(primary_key=True, index=True)
    channel: Mapped[str] = mapped_column(
        String(3), primary_key=True, default="fbo", server_default="fbo"
    )
    nm_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
