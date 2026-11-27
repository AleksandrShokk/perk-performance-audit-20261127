"""Read-only mobile supply feeds; existing financial/stock data is preserved."""

from alembic import op

revision = "0023_mobile_supplies"
down_revision = "0022_wb_stock_history"
branch_labels = depends_on = None
OLD = (
    "'catalog','sales','stocks','finance','orders','funnel',"
    "'returns','balance','prices','fbs','stock_history'"
)
NEW = OLD + ",'supply_demand','supplies'"


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
    for source in ("supply_demand", "supplies"):
        op.execute(f"""INSERT INTO sync_schedules (workspace_id,store_id,source,
                        requested_by,enabled,
                        next_refresh_at,next_attempt_at,reconcile_at)
            SELECT workspace_id,store_id,'{source}',requested_by,true,now(),now(),now()
            FROM sync_schedules WHERE source='stock_history' AND enabled ON CONFLICT DO NOTHING""")


def downgrade():
    for table in ("wb_records", "sync_schedules", "sync_runs"):
        op.execute(f"DELETE FROM {table} WHERE source IN ('supply_demand','supplies')")
    checks(OLD)
