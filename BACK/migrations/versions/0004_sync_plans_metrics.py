"""Store-scoped background plans and encrypted daily metrics."""

import sqlalchemy as sa
from alembic import op

revision = "0004_sync_plans_metrics"
down_revision = "0003_wb_sync"
branch_labels = None
depends_on = None


def store_fk():
    return sa.ForeignKeyConstraint(
        ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
    )


def upgrade():
    op.add_column(
        "sync_runs", sa.Column("sync_mode", sa.String(16), nullable=False, server_default="manual")
    )
    op.create_table(
        "sync_schedules",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("requested_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("recent_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column(
            "recent_completed", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("history_from", sa.Date()),
        sa.Column("backfill_to", sa.Date()),
        sa.Column("history_turn", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("backfill_chunk_days", sa.Integer(), nullable=False, server_default="31"),
        sa.Column("sales_cursor", sa.String(64)),
        sa.Column("next_refresh_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_completed_at", sa.DateTime(timezone=True)),
        sa.Column("reconcile_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.PrimaryKeyConstraint("workspace_id", "store_id", "source"),
        store_fk(),
        sa.CheckConstraint("source IN ('catalog', 'sales', 'stocks', 'finance')", name="source"),
        sa.CheckConstraint("recent_days BETWEEN 7 AND 30", name="recent_days"),
    )
    op.create_table(
        "wb_daily_metrics",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("dataset", sa.String(36), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("nm_id", sa.String(32), nullable=False),
        sa.Column("currency", sa.String(16), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint(
            "workspace_id", "store_id", "source", "dataset", "day", "nm_id", "currency"
        ),
        store_fk(),
        sa.CheckConstraint("source IN ('sales', 'finance')", name="source"),
    )
    op.create_table(
        "wb_metric_versions",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("warmed_version", sa.Uuid()),
        sa.PrimaryKeyConstraint("workspace_id", "store_id"),
        store_fk(),
    )
    for table in ("sync_schedules", "wb_daily_metrics", "wb_metric_versions"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        member = (
            f"EXISTS (SELECT 1 FROM memberships m WHERE m.workspace_id = {table}.workspace_id "
            "AND m.user_id = NULLIF(current_setting('perk.user_id', true), '')::uuid)"
        )
        owner = member[:-1] + " AND m.role = 'owner')"
        op.execute(f"CREATE POLICY tenant_read ON {table} FOR SELECT USING ({member})")
        op.execute(f"CREATE POLICY tenant_insert ON {table} FOR INSERT WITH CHECK ({owner})")
        op.execute(
            f"CREATE POLICY tenant_update ON {table} FOR UPDATE "
            f"USING ({owner}) WITH CHECK ({owner})"
        )
        op.execute(f"CREATE POLICY tenant_delete ON {table} FOR DELETE USING ({owner})")


def downgrade():
    op.drop_table("wb_metric_versions")
    op.drop_table("wb_daily_metrics")
    op.drop_table("sync_schedules")
    op.drop_column("sync_runs", "sync_mode")
