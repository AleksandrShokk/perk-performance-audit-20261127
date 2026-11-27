"""Read-only prices/FBS imports and independent daily stock history."""

import sqlalchemy as sa
from alembic import op

revision = "0021_inventory_channels"
down_revision = "0020_catalog_overrides"
branch_labels = depends_on = None
OLD = "'catalog', 'sales', 'stocks', 'finance', 'orders', 'funnel', 'returns', 'balance'"
NEW = OLD + ", 'prices', 'fbs'"


def checks(sources):
    for table in ("wb_records", "sync_schedules"):
        op.drop_constraint(op.f(f"ck_{table}_source"), table, type_="check")
        op.create_check_constraint("source", table, f"source IN ({sources})")
    op.drop_index("uq_sync_runs_active_source", table_name="sync_runs")
    op.create_index(
        "uq_sync_runs_active_source",
        "sync_runs",
        ["workspace_id", "store_id", "source"],
        unique=True,
        postgresql_where=f"status IN ('queued', 'running') AND source IN ({sources})",
    )


def upgrade():
    checks(NEW)
    op.add_column(
        "inventory_snapshots",
        sa.Column("channel", sa.String(3), nullable=False, server_default="fbo"),
    )
    op.drop_constraint("pk_inventory_snapshots", "inventory_snapshots", type_="primary")
    op.create_primary_key(
        "pk_inventory_snapshots",
        "inventory_snapshots",
        ["workspace_id", "store_id", "day", "nm_id", "channel"],
    )
    op.create_check_constraint("channel", "inventory_snapshots", "channel IN ('fbo', 'fbs')")
    # Seed independent plans only where stock imports were explicitly enabled.
    # The normal scheduler checks the credential scopes before any provider call.
    for source in ("prices", "fbs"):
        op.execute(f"""INSERT INTO sync_schedules (workspace_id,store_id,source,requested_by,
                enabled,
                next_refresh_at,next_attempt_at,reconcile_at)
            SELECT workspace_id,store_id,'{source}',requested_by,true,now(),now(),now()
            FROM sync_schedules WHERE source='stocks' AND enabled ON CONFLICT DO NOTHING""")


def downgrade():
    op.execute("DELETE FROM inventory_snapshots WHERE channel='fbs'")
    op.drop_constraint("ck_inventory_snapshots_channel", "inventory_snapshots", type_="check")
    op.drop_constraint("pk_inventory_snapshots", "inventory_snapshots", type_="primary")
    op.create_primary_key(
        "pk_inventory_snapshots",
        "inventory_snapshots",
        ["workspace_id", "store_id", "day", "nm_id"],
    )
    op.drop_column("inventory_snapshots", "channel")
    for table in ("wb_records", "sync_schedules", "sync_runs"):
        op.execute(f"DELETE FROM {table} WHERE source IN ('prices','fbs')")
    checks(OLD)
