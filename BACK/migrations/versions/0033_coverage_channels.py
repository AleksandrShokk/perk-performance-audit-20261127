"""Read WB FBS demand independently, preserving marketplace channel boundaries."""

from alembic import op

revision = "0033_coverage_channels"
down_revision = "0032_catalog_matches"
branch_labels = depends_on = None
OLD = (
    "'catalog','sales','stocks','finance','orders','funnel','returns','balance',"
    "'prices','fbs','stock_history','supply_demand','supplies'"
)
NEW = OLD + ",'fbs_demand'"


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
        postgresql_where=f"status IN ('queued','running') AND source IN ({sources})",
    )


def upgrade():
    checks(NEW)
    op.execute("""INSERT INTO sync_schedules(workspace_id,store_id,source,requested_by,enabled,
        next_refresh_at,next_attempt_at,reconcile_at)
        SELECT workspace_id,store_id,'fbs_demand',requested_by,true,now(),now(),now()
        FROM sync_schedules WHERE source='stock_history' AND enabled ON CONFLICT DO NOTHING""")
    # Refresh the recent sales slice, not years of history, to add the channel counters.
    op.execute("""UPDATE ozon_analytics_sync SET next_attempt_at=now(),status='pending'
        WHERE source='sales' AND status IN ('ready','error')""")


def downgrade():
    for table in ("wb_records", "sync_schedules", "sync_runs"):
        op.execute(f"DELETE FROM {table} WHERE source='fbs_demand'")
    checks(OLD)
