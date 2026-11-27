"""WB card funnel source: allow 'funnel' in sync plans, runs, records and daily aggregates."""

from alembic import op

revision = "0014_wb_funnel"
down_revision = "0013_wb_orders"
branch_labels = None
depends_on = None

OLD = "'catalog', 'sales', 'stocks', 'finance', 'orders'"
NEW = OLD + ", 'funnel'"


def checks(sources, metrics):
    for table in ("wb_records", "sync_schedules"):
        op.drop_constraint(op.f(f"ck_{table}_source"), table, type_="check")
        op.create_check_constraint("source", table, f"source IN ({sources})")
    op.drop_constraint(op.f("ck_wb_daily_metrics_source"), "wb_daily_metrics", type_="check")
    op.create_check_constraint("source", "wb_daily_metrics", f"source IN ({metrics})")
    op.drop_index("uq_sync_runs_active_source", table_name="sync_runs")
    op.create_index(
        "uq_sync_runs_active_source",
        "sync_runs",
        ["workspace_id", "store_id", "source"],
        unique=True,
        postgresql_where=f"status IN ('queued', 'running') AND source IN ({sources})",
    )


def upgrade():
    checks(NEW, "'sales', 'finance', 'orders', 'funnel'")


def downgrade():
    for table in ("wb_daily_metrics", "wb_records", "sync_schedules", "sync_runs"):
        op.execute(f"DELETE FROM {table} WHERE source = 'funnel'")
    checks(OLD, "'sales', 'finance', 'orders'")
