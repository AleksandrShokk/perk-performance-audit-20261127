"""WB returns to the seller: allow 'returns' in sync plans, runs and records."""

from alembic import op

revision = "0015_wb_returns"
down_revision = "0014_wb_funnel"
branch_labels = None
depends_on = None

OLD = "'catalog', 'sales', 'stocks', 'finance', 'orders', 'funnel'"
NEW = OLD + ", 'returns'"


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


def downgrade():
    for table in ("wb_records", "sync_schedules", "sync_runs"):
        op.execute(f"DELETE FROM {table} WHERE source = 'returns'")
    checks(OLD)
