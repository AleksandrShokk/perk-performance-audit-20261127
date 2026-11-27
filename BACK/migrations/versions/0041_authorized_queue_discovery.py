"""Discover only active owners' connected stores, without exposing queue data."""

from alembic import op

revision = "0041_authorized_queue_discovery"
down_revision = "0040_rejected_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE OR REPLACE FUNCTION perk_queue_actors(queue text) RETURNS SETOF uuid
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
      SELECT DISTINCT q.actor FROM (
        SELECT requested_by AS actor,workspace_id,store_id FROM sync_runs
          WHERE queue IN ('sync','warm') AND (queue='warm' OR
            (status IN ('queued','running') AND next_attempt_at<=now()))
        UNION ALL SELECT requested_by,workspace_id,store_id FROM ozon_analytics_sync
          WHERE queue='ozon_analytics' AND next_attempt_at<=now()
        UNION ALL SELECT requested_by,workspace_id,store_id FROM ozon_catalog_sync
          WHERE queue='ozon_catalog' AND next_attempt_at<=now()
        UNION ALL SELECT requested_by,workspace_id,store_id FROM supply_destination_sync
          WHERE queue='destinations' AND next_attempt_at<=now()
      ) q JOIN memberships m ON m.user_id=q.actor AND m.workspace_id=q.workspace_id
        JOIN users u ON u.id=q.actor
        JOIN stores s ON s.id=q.store_id AND s.workspace_id=q.workspace_id
      WHERE m.role IN ('owner','admin') AND u.is_active AND u.email_verified_at IS NOT NULL
        AND s.is_active AND s.connection_status='connected' LIMIT 1000
    $$;
    """)


def downgrade():
    pass  # Keep the stricter discovery predicate on downgrade as well.
