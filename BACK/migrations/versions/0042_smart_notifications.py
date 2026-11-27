"""Notification preferences, incident state and per-device delivery tracking."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0042_smart_notifications"
down_revision = "0041_authorized_queue_discovery"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "notifications",
        sa.Column("required_permissions", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "notifications",
        sa.Column("source_store_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    # The dispatcher cannot enumerate users through forced RLS. Expose only eligible
    # recipient IDs; every report and every delivery still runs as that recipient.
    op.execute("""
    CREATE FUNCTION perk_notification_users() RETURNS SETOF uuid
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
      SELECT DISTINCT u.id FROM users u
        JOIN memberships m ON m.user_id=u.id
        JOIN stores s ON s.workspace_id=m.workspace_id
      WHERE u.is_active AND u.email_verified_at IS NOT NULL
        AND s.is_active AND s.marketplace IN ('wildberries','ozon')
      LIMIT 1000
    $$;
    REVOKE ALL ON FUNCTION perk_notification_users() FROM PUBLIC;
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='perk_app') THEN
        GRANT EXECUTE ON FUNCTION perk_notification_users() TO perk_app;
      END IF;
    END $$;
    """)
    for _name, column in [
        (
            "categories",
            sa.Column("categories", postgresql.JSONB(), nullable=False, server_default="{}"),
        ),
        (
            "timezone",
            sa.Column("timezone", sa.String(64), nullable=False, server_default="Europe/Moscow"),
        ),
        (
            "digest_mode",
            sa.Column("digest_mode", sa.String(16), nullable=False, server_default="morning"),
        ),
        (
            "quiet_start",
            sa.Column("quiet_start", sa.Integer(), nullable=False, server_default="22"),
        ),
        ("quiet_end", sa.Column("quiet_end", sa.Integer(), nullable=False, server_default="9")),
        (
            "show_details",
            sa.Column("show_details", sa.Boolean(), nullable=False, server_default=sa.false()),
        ),
    ]:
        op.add_column("notification_settings", column)
    op.add_column("notifications", sa.Column("incident_key", sa.String(64), nullable=True))
    op.add_column(
        "notifications", sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "notifications", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "notifications",
        sa.Column("delivery_state", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index(
        "ix_notifications_active_incident",
        "notifications",
        ["user_id", "incident_key", "resolved_at"],
    )
    op.add_column(
        "push_devices",
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("auth_sessions.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )

    op.add_column(
        "push_devices", sa.Column("session_started_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade():
    op.drop_column("notifications", "required_permissions")
    op.drop_column("notifications", "source_store_ids")
    op.execute("DROP FUNCTION perk_notification_users()")
    op.drop_column("push_devices", "session_started_at")
    op.drop_column("push_devices", "session_id")
    op.drop_index("ix_notifications_active_incident", table_name="notifications")
    for field in ("delivery_state", "resolved_at", "acknowledged_at", "incident_key"):
        op.drop_column("notifications", field)
    for field in (
        "show_details",
        "quiet_end",
        "quiet_start",
        "digest_mode",
        "timezone",
        "categories",
    ):
        op.drop_column("notification_settings", field)
