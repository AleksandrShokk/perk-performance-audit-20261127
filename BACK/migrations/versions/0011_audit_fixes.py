"""Audit fixes: tax edit versioning, batched cleanup and indexes for expiry scans.

The runtime role runs with statement_timeout=5s and the whole function call is one
statement, so cleanup removes at most `batch` rows per table per call; the worker repeats.
"""

import sqlalchemy as sa
from alembic import op

revision = "0011_audit_fixes"
down_revision = "0010_insights_inventory"
branch_labels = None
depends_on = None

INDEXES = (
    ("ix_otp_challenges_expires_at", "otp_challenges", "expires_at"),
    ("ix_access_tokens_expires_at", "access_tokens", "expires_at"),
    ("ix_auth_sessions_expires_at", "auth_sessions", "expires_at"),
    ("ix_auth_sessions_revoked_at", "auth_sessions", "revoked_at"),
    ("ix_cost_imports_expires_at", "cost_imports", "expires_at"),
    ("ix_notifications_created_at", "notifications", "created_at"),
    ("ix_insight_snapshots_computed_at", "insight_snapshots", "computed_at"),
    ("ix_inventory_snapshots_day", "inventory_snapshots", "day"),
)

CLEANUP = """
CREATE FUNCTION perk_cleanup_expired(batch integer DEFAULT 5000) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE removed integer := 0; n integer; size integer := LEAST(GREATEST(batch, 1), 20000);
BEGIN
  DELETE FROM otp_challenges WHERE ctid IN (SELECT ctid FROM otp_challenges
    WHERE expires_at < now() - interval '1 day' LIMIT size);
  GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
  DELETE FROM access_tokens WHERE ctid IN (SELECT ctid FROM access_tokens
    WHERE expires_at < now() - interval '1 day' LIMIT size);
  GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
  -- Refresh tokens stay with their session for replay detection, then cascade.
  DELETE FROM auth_sessions WHERE ctid IN (SELECT ctid FROM auth_sessions
    WHERE expires_at < now() - interval '30 days' LIMIT size);
  GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
  DELETE FROM auth_sessions WHERE ctid IN (SELECT ctid FROM auth_sessions
    WHERE revoked_at < now() - interval '30 days' LIMIT size);
  GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
  DELETE FROM cost_imports WHERE ctid IN (SELECT ctid FROM cost_imports
    WHERE expires_at < now() - interval '1 day' LIMIT size);
  GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
  DELETE FROM notifications WHERE ctid IN (SELECT ctid FROM notifications
    WHERE created_at < now() - interval '90 days' LIMIT size);
  GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
  DELETE FROM insight_snapshots WHERE ctid IN (SELECT ctid FROM insight_snapshots
    WHERE computed_at < now() - interval '30 days' LIMIT size);
  GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
  DELETE FROM inventory_snapshots WHERE ctid IN (SELECT ctid FROM inventory_snapshots
    WHERE day < current_date - 800 LIMIT size);
  GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
  RETURN removed;
END $$
"""


def upgrade():
    op.add_column(
        "tax_settings",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    for name, table, column in INDEXES:
        op.create_index(name, table, [column])
    op.execute("DROP FUNCTION perk_cleanup_expired()")
    op.execute(CLEANUP)
    op.execute("REVOKE ALL ON FUNCTION perk_cleanup_expired(integer) FROM PUBLIC")


def downgrade():
    op.execute("DROP FUNCTION perk_cleanup_expired(integer)")
    for name, table, _ in INDEXES:
        op.drop_index(name, table_name=table)
    op.drop_column("tax_settings", "updated_at")
