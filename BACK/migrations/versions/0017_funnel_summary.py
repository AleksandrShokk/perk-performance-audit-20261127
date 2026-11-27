"""Deduplicate read-only funnel period jobs independently of daily imports."""

from alembic import op

revision = "0017_funnel_summary"
down_revision = "0016_wb_balance"
branch_labels = None
depends_on = None


def upgrade():
    # Main-chart days are capped at 28. Previous-period totals need no daily backfill.
    # An explicit previous-bars request can extend this floor later; published data stays.
    op.execute("""
        UPDATE sync_schedules
        SET history_from = GREATEST(history_from, (now() AT TIME ZONE 'Europe/Moscow')::date - 28)
        WHERE source = 'funnel' AND history_from IS NOT NULL
    """)
    op.create_index(
        "uq_sync_runs_active_funnel_summary",
        "sync_runs",
        ["workspace_id", "store_id", "date_from", "date_to"],
        unique=True,
        postgresql_where="source = 'funnel_summary' AND status IN ('queued', 'running')",
    )


def downgrade():
    op.drop_index("uq_sync_runs_active_funnel_summary", table_name="sync_runs")
