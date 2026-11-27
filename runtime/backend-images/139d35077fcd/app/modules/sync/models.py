import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, EntityMixin

SOURCES = (
    "source IN ('catalog', 'sales', 'stocks', 'finance', 'orders', 'funnel', "
    "'returns', 'balance', 'prices', 'fbs', 'stock_history', "
    "'supply_demand', 'fbs_demand', 'supplies')"
)


class SyncRun(EntityMixin, Base):
    __tablename__ = "sync_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "store_id"],
            ["stores.workspace_id", "stores.id"],
            ondelete="CASCADE",
            name="fk_sync_runs_workspace_store",
        ),
        UniqueConstraint("task_id", name="uq_sync_runs_task_id"),
        Index(
            "uq_sync_runs_active_funnel_summary",
            "workspace_id",
            "store_id",
            "date_from",
            "date_to",
            unique=True,
            postgresql_where=text("source = 'funnel_summary' AND status IN ('queued', 'running')"),
        ),
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="status"),
        CheckConstraint("records_processed >= 0", name="records_nonnegative"),
        Index("ix_sync_runs_workspace_store_created", "workspace_id", "store_id", "created_at"),
        UniqueConstraint("workspace_id", "store_id", "id", name="uq_sync_runs_tenant_id"),
        Index(
            "uq_sync_runs_active_source",
            "workspace_id",
            "store_id",
            "source",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running') AND " + SOURCES),
        ),
    )

    workspace_id: Mapped[uuid.UUID]
    store_id: Mapped[uuid.UUID]
    source: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), server_default="queued")
    task_id: Mapped[str | None] = mapped_column(String(255))
    records_processed: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    preview_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    date_from: Mapped[date | None] = mapped_column(Date)
    date_to: Mapped[date | None] = mapped_column(Date)
    cursor: Mapped[dict] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    pages_processed: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    sync_mode: Mapped[str] = mapped_column(String(16), server_default="manual")


class WBRecord(Base):
    __tablename__ = "wb_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
        CheckConstraint(SOURCES, name="source"),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    store_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(16), primary_key=True)
    record_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WBStagedRecord(Base):
    __tablename__ = "wb_staged_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "store_id", "run_id"],
            ["sync_runs.workspace_id", "sync_runs.store_id", "sync_runs.id"],
            ondelete="CASCADE",
        ),
    )
    workspace_id: Mapped[uuid.UUID]
    store_id: Mapped[uuid.UUID]
    run_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    record_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)


class SyncSchedule(Base):
    __tablename__ = "sync_schedules"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
        CheckConstraint(SOURCES, name="source"),
        CheckConstraint("recent_days BETWEEN 7 AND 30", name="recent_days"),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    store_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(16), primary_key=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    recent_days: Mapped[int] = mapped_column(Integer, server_default="7")
    recent_completed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    history_from: Mapped[date | None] = mapped_column(Date)
    backfill_to: Mapped[date | None] = mapped_column(Date)
    history_turn: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    backfill_chunk_days: Mapped[int] = mapped_column(Integer, server_default="31")
    sales_cursor: Mapped[str | None] = mapped_column(String(64))
    next_refresh_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reconcile_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))


class WBDailyMetric(Base):
    __tablename__ = "wb_daily_metrics"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
        CheckConstraint("source IN ('sales', 'finance', 'orders', 'funnel')", name="source"),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    store_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(16), primary_key=True)
    dataset: Mapped[str] = mapped_column(String(36), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    nm_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    currency: Mapped[str] = mapped_column(String(16), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)


class WBMetricVersion(Base):
    __tablename__ = "wb_metric_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    store_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    version: Mapped[uuid.UUID]
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    warmed_version: Mapped[uuid.UUID | None]
    format_version: Mapped[int] = mapped_column(Integer, server_default="1")
