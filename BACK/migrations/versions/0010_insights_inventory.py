"""Inventory snapshots, taxes, precomputed insights, journal, goals and notifications.

Store tables use the same forced RLS as other tenant data. Insight snapshots are a derived
cache, so any member may write them; deleting stays with owners. A SECURITY DEFINER function
lets the restricted runtime role delete only expired rows it otherwise cannot delete.
"""

import sqlalchemy as sa
from alembic import op

revision = "0010_insights_inventory"
down_revision = "0009_otp_auth"
branch_labels = None
depends_on = None

TENANT = ("inventory_snapshots", "tax_settings", "insight_snapshots", "store_events", "store_goals")


def tenant_columns():
    return [
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
    ]


def tenant_fk(table):
    return sa.ForeignKeyConstraint(
        ["workspace_id", "store_id"],
        ["stores.workspace_id", "stores.id"],
        name=op.f(f"fk_{table}_workspace_id_stores"),
        ondelete="CASCADE",
    )


def created_at():
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade():
    op.create_table(
        "inventory_snapshots",
        *tenant_columns(),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("nm_id", sa.String(32), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        tenant_fk("inventory_snapshots"),
        sa.PrimaryKeyConstraint(
            "workspace_id", "store_id", "day", "nm_id", name=op.f("pk_inventory_snapshots")
        ),
    )
    op.create_table(
        "tax_settings",
        *tenant_columns(),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("regime", sa.String(32), nullable=False),
        sa.Column("rate", sa.Numeric(5, 2), nullable=False),
        sa.Column("vat_rate", sa.Numeric(5, 2), nullable=False),
        sa.Column("income_base", sa.String(16), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        created_at(),
        sa.CheckConstraint(
            "regime IN ('none', 'usn_income', 'usn_income_expense', 'profit')",
            name=op.f("ck_tax_settings_regime"),
        ),
        sa.CheckConstraint(
            "income_base IN ('revenue', 'payout')", name=op.f("ck_tax_settings_income_base")
        ),
        sa.CheckConstraint(
            "rate >= 0 AND rate <= 100 AND vat_rate >= 0 AND vat_rate <= 100",
            name=op.f("ck_tax_settings_rates"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_tax_settings_created_by_users")
        ),
        tenant_fk("tax_settings"),
        sa.PrimaryKeyConstraint(
            "workspace_id", "store_id", "effective_from", name=op.f("pk_tax_settings")
        ),
    )
    op.create_table(
        "insight_snapshots",
        *tenant_columns(),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("params_key", sa.String(64), nullable=False),
        sa.Column("revision", sa.String(64), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        tenant_fk("insight_snapshots"),
        sa.PrimaryKeyConstraint(
            "workspace_id", "store_id", "kind", "params_key", name=op.f("pk_insight_snapshots")
        ),
    )
    op.create_table(
        "store_events",
        *tenant_columns(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("nm_id", sa.String(32), nullable=True),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        created_at(),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_store_events_created_by_users")
        ),
        tenant_fk("store_events"),
        sa.PrimaryKeyConstraint("workspace_id", "store_id", "id", name=op.f("pk_store_events")),
    )
    op.create_index(op.f("ix_store_events_day"), "store_events", ["day"])
    op.create_table(
        "store_goals",
        *tenant_columns(),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("metric", sa.String(16), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_store_goals_created_by_users")
        ),
        tenant_fk("store_goals"),
        sa.PrimaryKeyConstraint(
            "workspace_id", "store_id", "month", "metric", name=op.f("pk_store_goals")
        ),
    )

    for table in TENANT:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        member = (
            f"EXISTS (SELECT 1 FROM memberships m WHERE m.workspace_id = {table}.workspace_id "
            "AND m.user_id = NULLIF(current_setting('perk.user_id', true), '')::uuid)"
        )
        owner = member[:-1] + " AND m.role = 'owner')"
        writer = member if table == "insight_snapshots" else owner
        op.execute(f"CREATE POLICY tenant_read ON {table} FOR SELECT USING ({member})")
        op.execute(f"CREATE POLICY tenant_insert ON {table} FOR INSERT WITH CHECK ({writer})")
        op.execute(
            f"CREATE POLICY tenant_update ON {table} FOR UPDATE "
            f"USING ({writer}) WITH CHECK ({writer})"
        )
        op.execute(f"CREATE POLICY tenant_delete ON {table} FOR DELETE USING ({owner})")

    op.create_table(
        "notification_settings",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("telegram_chat_ciphertext", sa.Text(), nullable=True),
        sa.Column("telegram_linked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("digest_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("digest_hour", sa.Integer(), server_default=sa.text("9"), nullable=False),
        sa.Column("alerts_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("telegram_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("push_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_digest_on", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notification_settings_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_notification_settings")),
    )
    op.create_table(
        "notifications",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("store_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("dedupe_key", sa.String(64), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        created_at(),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notifications_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_notifications_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            name=op.f("fk_notifications_store_id_stores"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint("user_id", "dedupe_key", name=op.f("uq_notifications_user_id")),
    )
    op.create_index(op.f("ix_notifications_user_id"), "notifications", ["user_id"])
    op.create_table(
        "push_devices",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_digest", sa.String(64), nullable=False),
        sa.Column("token_ciphertext", sa.Text(), nullable=False),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        created_at(),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_push_devices_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_push_devices")),
        sa.UniqueConstraint("token_digest", name=op.f("uq_push_devices_token_digest")),
    )
    op.create_index(op.f("ix_push_devices_user_id"), "push_devices", ["user_id"])

    # Owned by the migration (admin) role; the runtime role may only EXECUTE it.
    op.execute(
        """
        CREATE FUNCTION perk_cleanup_expired() RETURNS integer
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE removed integer := 0; n integer;
        BEGIN
          DELETE FROM otp_challenges WHERE expires_at < now() - interval '1 day';
          GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
          DELETE FROM access_tokens WHERE expires_at < now() - interval '1 day';
          GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
          -- Refresh tokens stay with their session for replay detection, then cascade.
          DELETE FROM auth_sessions
            WHERE expires_at < now() - interval '30 days'
               OR revoked_at < now() - interval '30 days';
          GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
          DELETE FROM cost_imports WHERE expires_at < now() - interval '1 day';
          GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
          DELETE FROM notifications WHERE created_at < now() - interval '90 days';
          GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
          DELETE FROM insight_snapshots WHERE computed_at < now() - interval '30 days';
          GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
          DELETE FROM inventory_snapshots WHERE day < current_date - interval '800 days';
          GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
          RETURN removed;
        END $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION perk_cleanup_expired() FROM PUBLIC")


def downgrade():
    op.execute("DROP FUNCTION IF EXISTS perk_cleanup_expired()")
    for table in (
        "push_devices",
        "notifications",
        "notification_settings",
        "store_goals",
        "store_events",
        "insight_snapshots",
        "tax_settings",
        "inventory_snapshots",
    ):
        op.drop_table(table)
