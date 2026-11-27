"""Ozon accruals and buyer prices, with distinct finance/analytics permissions."""

import sqlalchemy as sa
from alembic import op

revision = "0026_ozon_finance"
down_revision = "0025_ozon_analytics"
branch_labels = depends_on = None


def upgrade():
    for table, permission in (
        ("marketplace_finance_days", "finance.read"),
        ("marketplace_realizations", "analytics.read"),
    ):
        extra = (
            [
                sa.Column("posting_key", sa.String(64), primary_key=True),
                sa.Column("sku", sa.String(32), primary_key=True),
            ]
            if table.endswith("realizations")
            else [sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False)]
        )
        op.create_table(
            table,
            sa.Column("workspace_id", sa.Uuid(), primary_key=True),
            sa.Column("store_id", sa.Uuid(), primary_key=True),
            sa.Column("day", sa.Date(), primary_key=True),
            *extra,
            sa.Column("ciphertext", sa.Text(), nullable=False),
            sa.ForeignKeyConstraint(
                ["workspace_id", "store_id"],
                ["stores.workspace_id", "stores.id"],
                ondelete="CASCADE",
            ),
        )
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        scope = "perk_store_access(workspace_id,store_id)"
        reader = scope + f" AND perk_permission(workspace_id,'{permission}')"
        writer = scope + " AND perk_is_member(workspace_id,'owner')"
        op.execute(f"CREATE POLICY tenant_read ON {table} FOR SELECT USING ({reader})")
        op.execute(f"CREATE POLICY tenant_insert ON {table} FOR INSERT WITH CHECK ({writer})")
        op.execute(
            f"CREATE POLICY tenant_update ON {table} FOR UPDATE "
            f"USING ({writer}) WITH CHECK ({writer})"
        )
        op.execute(f"CREATE POLICY tenant_delete ON {table} FOR DELETE USING ({writer})")
    op.create_index(
        "ix_marketplace_realizations_posting",
        "marketplace_realizations",
        ["workspace_id", "store_id", "posting_key"],
    )
    op.drop_constraint(op.f("ck_ozon_analytics_sync_source"), "ozon_analytics_sync", type_="check")
    op.create_check_constraint(
        "source", "ozon_analytics_sync", "source IN ('sales','stock_cover','finance')"
    )
    op.execute("""INSERT INTO ozon_analytics_sync
        (workspace_id,store_id,source,requested_by,status,next_attempt_at,records_processed,history_from,cursor)
        SELECT workspace_id,store_id,'finance',requested_by,'pending',now(),0,history_from,
        (now() AT TIME ZONE 'Europe/Moscow')::date-1 FROM ozon_analytics_sync WHERE source='sales'
        ON CONFLICT DO NOTHING""")
    # Rebuild confirmed order cohorts using buyer prices. Preserve previous database data.
    op.execute("""UPDATE ozon_analytics_sync SET status='pending',run_id=NULL,next_attempt_at=now(),
        updated_at=NULL,cursor=(now() AT TIME ZONE 'Europe/Moscow')::date-1 WHERE source='sales'""")


def downgrade():
    op.execute("DELETE FROM ozon_analytics_sync WHERE source='finance'")
    op.drop_constraint(op.f("ck_ozon_analytics_sync_source"), "ozon_analytics_sync", type_="check")
    op.create_check_constraint("source", "ozon_analytics_sync", "source IN ('sales','stock_cover')")
    op.drop_table("marketplace_realizations")
    op.drop_table("marketplace_finance_days")
