"""Bound diagnostic and abandoned-row retention; preserve successful coverage history."""

from alembic import op

revision = "0039_import_retention"
down_revision = "0038_import_issues"
branch_labels = None
depends_on = None


def upgrade():
    # Extend the existing bounded cleanup, preserving its body and grants.
    bind = op.get_bind()
    source = bind.exec_driver_sql(
        "SELECT pg_get_functiondef('perk_cleanup_expired(integer)'::regprocedure)"
    ).scalar_one()
    extra = """
    DELETE FROM import_issues WHERE ctid IN (SELECT ctid FROM import_issues
      WHERE created_at<now()-interval '90 days' LIMIT size);
    GET DIAGNOSTICS n=ROW_COUNT; removed:=removed+n;
    DELETE FROM wb_staged_records WHERE ctid IN (SELECT s.ctid FROM wb_staged_records s
      JOIN sync_runs r ON r.id=s.run_id WHERE r.status IN ('succeeded','failed')
      AND r.finished_at<now()-interval '7 days' LIMIT size);
    GET DIAGNOSTICS n=ROW_COUNT; removed:=removed+n;
    DELETE FROM sync_runs WHERE ctid IN (SELECT r.ctid FROM sync_runs r
      WHERE status='failed' AND finished_at<now()-interval '90 days'
      AND NOT EXISTS(SELECT 1 FROM wb_daily_metrics m WHERE m.dataset=r.id::text) LIMIT size);
    GET DIAGNOSTICS n=ROW_COUNT; removed:=removed+n;
    """
    op.execute(source.replace("RETURN removed;", extra + " RETURN removed;"))


def downgrade():
    pass  # Retention never restores deleted diagnostics; published data was preserved.
