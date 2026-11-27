# ruff: noqa: E501
"""A stale task can only mark its own lease rejected, without access to tenant content."""

from alembic import op

revision = "0040_rejected_jobs"
down_revision = "0039_import_retention"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE FUNCTION perk_reject_ozon_job(ws uuid,sid uuid,src text,actor uuid,run uuid)
    RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
    BEGIN
      IF EXISTS(SELECT 1 FROM memberships m JOIN users u ON u.id=m.user_id
        JOIN stores s ON s.workspace_id=m.workspace_id
        WHERE m.user_id=actor AND m.workspace_id=ws AND s.id=sid
          AND m.role IN ('owner','admin') AND u.is_active AND u.email_verified_at IS NOT NULL
          AND s.is_active AND s.connection_status='connected') THEN RETURN; END IF;
      IF src='catalog' THEN
        UPDATE ozon_catalog_sync SET status='error',error_code='access_revoked',
          next_attempt_at=now()+interval '6 hours'
          WHERE workspace_id=ws AND store_id=sid AND run_id=run AND requested_by=actor;
      ELSE
        UPDATE ozon_analytics_sync SET status='error',error_code='access_revoked',
          next_attempt_at=now()+interval '6 hours'
          WHERE workspace_id=ws AND store_id=sid AND source=src AND run_id=run AND requested_by=actor;
      END IF;
    END $$;
    REVOKE ALL ON FUNCTION perk_reject_ozon_job(uuid,uuid,text,uuid,uuid) FROM PUBLIC;
    """)


def downgrade():
    op.execute("DROP FUNCTION perk_reject_ozon_job(uuid,uuid,text,uuid,uuid)")
