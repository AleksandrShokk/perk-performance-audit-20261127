import uuid

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, EntityMixin


class AuditEvent(EntityMixin, Base):
    __tablename__ = "audit_events"
    user_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    action: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[uuid.UUID | None]
    success: Mapped[bool]
