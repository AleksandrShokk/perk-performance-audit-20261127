"""Neutral daily analytics, native FBO coverage, and an identifier-only Ozon outbox."""

import sqlalchemy as sa
from alembic import op

revision = "0025_ozon_analytics"
down_revision = "0024_ozon_catalog"
branch_labels = depends_on = None


def upgrade():
    for table, permission in (
        ("marketplace_sales_days", "analytics.read"),
        ("marketplace_stock_cover", "inventory.read"),
    ):
        columns = [sa.Column("day", sa.Date(), primary_key=True)] if table.endswith("days") else []
        op.create_table(
            table,
            sa.Column("workspace_id", sa.Uuid(), primary_key=True),
            sa.Column("store_id", sa.Uuid(), primary_key=True),
            *columns,
            sa.Column("ciphertext", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["workspace_id", "store_id"],
                ["stores.workspace_id", "stores.id"],
                ondelete="CASCADE",
            ),
        )
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        scope = "perk_store_access(workspace_id,store_id)"
        read = scope + f" AND perk_permission(workspace_id,'{permission}')"
        writer = scope + " AND perk_is_member(workspace_id,'owner')"
        op.execute(f"CREATE POLICY tenant_read ON {table} FOR SELECT USING ({read})")
        op.execute(f"CREATE POLICY tenant_insert ON {table} FOR INSERT WITH CHECK ({writer})")
        op.execute(
            f"CREATE POLICY tenant_update ON {table} FOR UPDATE "
            f"USING ({writer}) WITH CHECK ({writer})"
        )
    op.create_table(
        "ozon_analytics_sync",
        sa.Column("workspace_id", sa.Uuid(), primary_key=True),
        sa.Column("store_id", sa.Uuid(), primary_key=True),
        sa.Column("source", sa.String(16), primary_key=True),
        sa.Column("requested_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("run_id", sa.Uuid()),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("records_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(64)),
        sa.Column("history_from", sa.Date()),
        sa.Column("cursor", sa.Date()),
        sa.Column("date_from", sa.Date()),
        sa.Column("date_to", sa.Date()),
        sa.Column("mode", sa.String(16), nullable=False, server_default="history"),
        sa.CheckConstraint("source IN ('sales','stock_cover')", name="source"),
        sa.CheckConstraint(
            "status IN ('pending','queued','running','ready','error')", name="status"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
    )
    op.create_index("ix_ozon_analytics_due", "ozon_analytics_sync", ["next_attempt_at"])
    # Refresh catalogs once to retain the provider's per-channel SKU mapping.
    op.execute("UPDATE ozon_catalog_sync SET status='pending', run_id=NULL, next_attempt_at=now()")
    # Outbox contains no seller records or secrets. Runtime workers reauthorize every row.
    for source in ("sales", "stock_cover"):
        op.execute(f"""INSERT INTO ozon_analytics_sync
            (workspace_id,store_id,source,requested_by,status,next_attempt_at,records_processed,history_from,cursor)
            SELECT DISTINCT ON (s.id) s.workspace_id,s.id,'{source}',m.user_id,'pending',now(),0,
            (now() AT TIME ZONE 'Europe/Moscow')::date-180,
            (now() AT TIME ZONE 'Europe/Moscow')::date-1
            FROM stores s JOIN memberships m ON m.workspace_id=s.workspace_id
            JOIN users u ON u.id=m.user_id WHERE s.marketplace='ozon' AND s.is_active
            AND s.connection_status='connected' AND m.role IN ('owner','admin')
            AND u.is_active AND u.email_verified_at IS NOT NULL
            ORDER BY s.id,CASE m.role WHEN 'owner' THEN 0 ELSE 1 END,m.user_id
            ON CONFLICT DO NOTHING""")


def downgrade():
    op.drop_table("ozon_analytics_sync")
    op.drop_table("marketplace_stock_cover")
    op.drop_table("marketplace_sales_days")
