# ruff: noqa: E501
"""Readers may extend the configured owner's import range without direct outbox writes."""

from alembic import op

revision = "0037_audit_history_requests"
down_revision = "0036_audit_outbox_rls"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE FUNCTION perk_ozon_request_history(ws uuid,sid uuid,src text,start date,finish date,
        reprice boolean DEFAULT false) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
    BEGIN
      IF NOT perk_store_access(ws,sid) OR src NOT IN ('sales','finance','traffic') OR
        NOT perk_permission(ws,CASE WHEN src='finance' THEN 'finance.read' ELSE 'analytics.read' END)
        OR start>finish OR finish>current_date OR start<current_date-1099 THEN RETURN; END IF;
      UPDATE ozon_analytics_sync SET
        history_from=LEAST(COALESCE(history_from,start),start),
        cursor=CASE WHEN cursor IS NOT NULL THEN cursor
          WHEN reprice AND status NOT IN ('pending','queued','running') THEN finish
          WHEN history_from IS NULL OR start<history_from THEN COALESCE(history_from-1,current_date-1)
          ELSE cursor END,
        status=CASE WHEN cursor IS NULL AND status NOT IN ('queued','running') THEN 'pending' ELSE status END,
        next_attempt_at=CASE WHEN cursor IS NULL AND status NOT IN ('queued','running') THEN now() ELSE next_attempt_at END,
        error_code=CASE WHEN reprice AND status NOT IN ('pending','queued','running') THEN NULL ELSE error_code END
      WHERE workspace_id=ws AND store_id=sid AND source=src AND
        (history_from IS NULL OR start<history_from OR reprice AND cursor IS NULL AND status NOT IN ('pending','queued','running'));
    END $$;
    REVOKE ALL ON FUNCTION perk_ozon_request_history(uuid,uuid,text,date,date,boolean) FROM PUBLIC;
    CREATE OR REPLACE FUNCTION perk_sync_actor(run uuid, task text) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
    DECLARE job sync_runs%ROWTYPE;
    BEGIN
      SELECT * INTO job FROM sync_runs WHERE id=run AND task_id=task AND status IN ('queued','running');
      IF NOT FOUND THEN RETURN NULL; END IF;
      IF NOT EXISTS (SELECT 1 FROM memberships m JOIN users u ON u.id=m.user_id
          WHERE m.workspace_id=job.workspace_id AND m.user_id=job.requested_by
          AND m.role IN ('owner','admin') AND u.is_active AND u.email_verified_at IS NOT NULL) THEN
        UPDATE sync_runs SET status='failed',error_code='sync_permission_revoked',finished_at=now(),task_id=NULL WHERE id=run;
        DELETE FROM wb_staged_records WHERE run_id=run;
        DELETE FROM wb_daily_metrics WHERE dataset=run::text;
        RETURN NULL;
      END IF;
      RETURN job.requested_by;
    END $$;
    """)


def downgrade():
    op.execute("DROP FUNCTION perk_ozon_request_history(uuid,uuid,text,date,date,boolean)")
