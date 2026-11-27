"""Explicit warehouse semantics for combined marketplace inventory."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class InventorySettings(Base):
    __tablename__ = "inventory_settings"
    __table_args__ = (CheckConstraint("fbs_mode IN ('separate','shared')", name="fbs_mode"),)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    fbs_mode: Mapped[str] = mapped_column(String(16))
    updated_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
