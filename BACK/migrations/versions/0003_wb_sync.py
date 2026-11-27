"""Resumable WB imports and encrypted tenant-scoped data."""

import sqlalchemy as sa
from alembic import op

revision = "0003_wb_sync"
down_revision = "d15d53b7d3d9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sync_runs", sa.Column("requested_by", sa.Uuid(), sa.ForeignKey("users.id")))
    op.add_column("sync_runs", sa.Column("date_from", sa.Date()))
    op.add_column("sync_runs", sa.Column("date_to", sa.Date()))
    op.add_column(
        "sync_runs", sa.Column("cursor", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
    )
    op.add_column(
        "sync_runs", sa.Column("pages_processed", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "sync_runs", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "sync_runs",
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint(
        "uq_sync_runs_tenant_id", "sync_runs", ["workspace_id", "store_id", "id"]
    )
    op.create_index(
        "uq_sync_runs_active_source",
        "sync_runs",
        ["workspace_id", "store_id", "source"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('queued', 'running') "
            "AND source IN ('catalog', 'sales', 'stocks', 'finance')"
        ),
    )
    op.create_table(
        "wb_records",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("record_key", sa.String(128), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", "store_id", "source", "record_key"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint("source IN ('catalog', 'sales', 'stocks', 'finance')", name="source"),
    )
    op.create_table(
        "wb_staged_records",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("record_key", sa.String(128), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("run_id", "record_key"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "store_id", "run_id"],
            ["sync_runs.workspace_id", "sync_runs.store_id", "sync_runs.id"],
            ondelete="CASCADE",
        ),
    )
    # The app role cannot bypass RLS. Worker sets the initiating owner for each transaction.
    for table in ("wb_records", "wb_staged_records"):
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
    op.drop_table("wb_staged_records")
    op.drop_table("wb_records")
    op.drop_index("uq_sync_runs_active_source", table_name="sync_runs")
    op.drop_constraint("uq_sync_runs_tenant_id", "sync_runs", type_="unique")
    for column in (
        "next_attempt_at",
        "attempts",
        "pages_processed",
        "cursor",
        "date_to",
        "date_from",
        "requested_by",
    ):
        op.drop_column("sync_runs", column)
