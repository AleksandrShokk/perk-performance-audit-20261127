"""Tenant isolation for outboxes and notifications; narrowly scoped worker discovery."""

from alembic import op

revision = "0036_audit_outbox_rls"
down_revision = "0035_funnel_requested_history"
branch_labels = None
depends_on = None

TABLES = ["sync_runs", "ozon_analytics_sync", "ozon_catalog_sync", "supply_destination_sync"]


def upgrade():
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_read ON {table} FOR SELECT USING "
            "(perk_store_access(workspace_id,store_id))"
        )
        writer = "perk_store_access(workspace_id,store_id) AND perk_is_member(workspace_id,'owner')"
        op.execute(
            f"CREATE POLICY tenant_write ON {table} FOR ALL USING ({writer}) WITH CHECK ({writer})"
        )
    op.execute("ALTER TABLE notifications ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE notifications FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY own_notification ON notifications FOR ALL "
        "USING (user_id=perk_actor()) WITH CHECK (user_id=perk_actor())"
    )
    op.execute("""
    CREATE FUNCTION perk_queue_actors(queue text) RETURNS SETOF uuid
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
      SELECT DISTINCT q.actor FROM (
        SELECT requested_by AS actor FROM sync_runs
          WHERE queue IN ('sync','warm') AND (queue='warm' OR
            (status IN ('queued','running') AND next_attempt_at<=now()))
        UNION ALL SELECT requested_by FROM ozon_analytics_sync
          WHERE queue='ozon_analytics' AND next_attempt_at<=now()
        UNION ALL SELECT requested_by FROM ozon_catalog_sync
          WHERE queue='ozon_catalog' AND next_attempt_at<=now()
        UNION ALL SELECT requested_by FROM supply_destination_sync
          WHERE queue='destinations' AND next_attempt_at<=now()
      ) q WHERE q.actor IS NOT NULL LIMIT 1000
    $$;
    CREATE FUNCTION perk_sync_actor(run uuid, task text) RETURNS uuid
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
      SELECT requested_by FROM sync_runs WHERE id=run AND task_id=task
        AND status IN ('queued','running')
    $$;
    REVOKE ALL ON FUNCTION perk_queue_actors(text), perk_sync_actor(uuid,text) FROM PUBLIC;

    """)


def downgrade():
    op.execute("DROP FUNCTION perk_sync_actor(uuid,text)")
    op.execute("DROP FUNCTION perk_queue_actors(text)")
    for table in TABLES:
        op.execute(f"DROP POLICY tenant_read ON {table}")
        op.execute(f"DROP POLICY tenant_write ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY own_notification ON notifications")
    op.execute("ALTER TABLE notifications DISABLE ROW LEVEL SECURITY")
