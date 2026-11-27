"""Enable the WB historical inventory report without resetting existing data."""

from alembic import op

revision = "0022_wb_stock_history"
down_revision = "0021_inventory_channels"
branch_labels = depends_on = None
OLD = (
    "'catalog', 'sales', 'stocks', 'finance', 'orders', 'funnel', "
    "'returns', 'balance', 'prices', 'fbs'"
)
NEW = OLD + ", 'stock_history'"


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
    # Existing explicitly enabled stock/funnel imports also request the history.
    # Prefer the stock plan when both exist. The scheduler verifies access afresh.
    op.execute("""INSERT INTO sync_schedules
        (workspace_id,store_id,source,requested_by,enabled,recent_days,
         next_refresh_at,next_attempt_at,reconcile_at)
        SELECT DISTINCT ON (workspace_id,store_id)
            workspace_id,store_id,'stock_history',requested_by,true,28,now(),now(),now()
        FROM sync_schedules WHERE source IN ('stocks','funnel') AND enabled
        ORDER BY workspace_id,store_id,CASE WHEN source='stocks' THEN 0 ELSE 1 END
        ON CONFLICT DO NOTHING""")


def downgrade():
    for table in ("wb_records", "sync_schedules", "sync_runs"):
        op.execute(f"DELETE FROM {table} WHERE source='stock_history'")
    checks(OLD)
