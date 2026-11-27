"""Extend the owner's import plan when an authorized reader selects older analytics."""

from alembic import op

revision = "0035_funnel_requested_history"
down_revision = "0034_catalog_group_reset"
branch_labels = depends_on = None


def upgrade():
    op.execute("""CREATE FUNCTION perk_request_funnel_history(ws uuid,sid uuid,requested date)
    RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
    DECLARE today date := (now() AT TIME ZONE 'Europe/Moscow')::date;
            oldest date := GREATEST(requested,today-359);
    BEGIN
      IF NOT perk_store_access(ws,sid) OR NOT perk_permission(ws,'analytics.read')
        OR requested IS NULL OR requested>=today THEN RETURN false; END IF;
      UPDATE sync_schedules SET
        backfill_to=GREATEST(backfill_to,COALESCE(history_from,today-7)-1),
        history_from=LEAST(COALESCE(history_from,oldest),oldest),
        next_attempt_at=LEAST(next_attempt_at,now())
      WHERE workspace_id=ws AND store_id=sid AND source='funnel' AND enabled
        AND (history_from IS NULL OR history_from>oldest);
      RETURN FOUND;
    END $$""")


def downgrade():
    op.execute("DROP FUNCTION perk_request_funnel_history(uuid,uuid,date)")
