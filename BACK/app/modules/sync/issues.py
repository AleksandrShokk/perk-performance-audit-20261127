"""Store only scoped record identifiers and reasons; never log a provider's raw row."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKeyConstraint, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ImportIssue(Base):
    __tablename__ = "import_issues"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
        UniqueConstraint("workspace_id", "store_id", "source", "record_key"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID]
    store_id: Mapped[uuid.UUID]
    source: Mapped[str] = mapped_column(String(32))
    record_key: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(64))
    ciphertext: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def retain(db, vault, wid, sid, source, identifier, reason):
    identifier = str(identifier)[:128]
    key = vault.digest("import-issue", f"{wid}:{sid}:{source}:{identifier}")
    aad = f"import-issue:{wid}:{sid}:{source}:{key}"
    statement = insert(ImportIssue).values(
        id=uuid.uuid4(),
        workspace_id=wid,
        store_id=sid,
        source=source,
        record_key=key,
        reason=reason,
        ciphertext=vault.seal(identifier, aad),
    )
    db.execute(
        statement.on_conflict_do_update(
            index_elements=["workspace_id", "store_id", "source", "record_key"],
            set_={
                "reason": reason,
                "ciphertext": statement.excluded.ciphertext,
                "created_at": func.now(),
            },
        )
    )
