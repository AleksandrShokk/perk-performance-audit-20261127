"""Native Ozon traffic/supplies, independent quotas and refreshed product accrual details."""

import sqlalchemy as sa
from alembic import op

revision = "0028_ozon_parity"
down_revision = "0027_ozon_costs_inventory"
branch_labels = depends_on = None


def upgrade():
    for table, permission in [
        ("marketplace_traffic_days", "analytics.read"),
        ("marketplace_supply_snapshots", "inventory.read"),
    ]:
        op.create_table(
            table,
            sa.Column("workspace_id", sa.Uuid(), primary_key=True),
            sa.Column("store_id", sa.Uuid(), primary_key=True),
            *([sa.Column("day", sa.Date(), primary_key=True)] if table.endswith("_days") else []),
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
        reader = (
            "perk_store_access(workspace_id,store_id) "
            f"AND perk_permission(workspace_id,'{permission}')"
        )
        writer = "perk_store_access(workspace_id,store_id) AND perk_is_member(workspace_id,'owner')"
        op.execute(f"CREATE POLICY tenant_read ON {table} FOR SELECT USING ({reader})")
        op.execute(f"CREATE POLICY tenant_insert ON {table} FOR INSERT WITH CHECK ({writer})")
        op.execute(
            f"CREATE POLICY tenant_update ON {table} FOR UPDATE "
            f"USING ({writer}) WITH CHECK ({writer})"
        )
        op.execute(f"CREATE POLICY tenant_delete ON {table} FOR DELETE USING ({writer})")
    op.execute("DROP POLICY tenant_read ON marketplace_catalog_snapshots")
    op.execute("""CREATE POLICY tenant_read ON marketplace_catalog_snapshots FOR SELECT USING (
        perk_store_access(workspace_id,store_id) AND
        (perk_permission(workspace_id,'inventory.read') OR
         perk_permission(workspace_id,'profit.read') OR
         perk_permission(workspace_id,'costs.write')))
    """)
    op.execute("DROP POLICY tenant_read ON marketplace_variant_costs")
    op.execute("""CREATE POLICY tenant_read ON marketplace_variant_costs FOR SELECT USING (
        perk_store_access(workspace_id,store_id) AND
        (perk_permission(workspace_id,'profit.read') OR
         perk_permission(workspace_id,'costs.write')))
    """)
    op.drop_constraint(op.f("ck_ozon_analytics_sync_source"), "ozon_analytics_sync", type_="check")
    op.create_check_constraint(
        "source",
        "ozon_analytics_sync",
        "source IN ('sales','stock_cover','finance','traffic','supplies')",
    )
    for source in ("traffic", "supplies"):
        op.execute(f"""INSERT INTO ozon_analytics_sync
            (workspace_id,store_id,source,requested_by,status,next_attempt_at,
             records_processed,history_from,cursor)
            SELECT workspace_id,store_id,'{source}',requested_by,'pending',now(),0,
            CASE WHEN '{source}'='traffic' THEN
              (now() AT TIME ZONE 'Europe/Moscow')::date-90 ELSE history_from END,
            (now() AT TIME ZONE 'Europe/Moscow')::date-1
            FROM ozon_analytics_sync WHERE source='sales'
            ON CONFLICT DO NOTHING""")
    op.execute("""UPDATE ozon_analytics_sync SET status='pending',run_id=NULL,next_attempt_at=now(),
        updated_at=NULL,cursor=(now() AT TIME ZONE 'Europe/Moscow')::date-1
        WHERE source='finance'""")


def downgrade():
    op.execute("DROP POLICY tenant_read ON marketplace_catalog_snapshots")
    op.execute("""CREATE POLICY tenant_read ON marketplace_catalog_snapshots FOR SELECT USING (
        perk_store_access(workspace_id,store_id) AND
        (perk_permission(workspace_id,'inventory.read') OR
         perk_permission(workspace_id,'profit.read')))
    """)
    op.execute("DROP POLICY tenant_read ON marketplace_variant_costs")
    op.execute("""CREATE POLICY tenant_read ON marketplace_variant_costs FOR SELECT USING (
        perk_store_access(workspace_id,store_id) AND perk_permission(workspace_id,'profit.read'))
    """)
    op.execute("DELETE FROM ozon_analytics_sync WHERE source IN ('traffic','supplies')")
    op.drop_constraint(op.f("ck_ozon_analytics_sync_source"), "ozon_analytics_sync", type_="check")
    op.create_check_constraint(
        "source", "ozon_analytics_sync", "source IN ('sales','stock_cover','finance')"
    )
    op.drop_table("marketplace_supply_snapshots")
    op.drop_table("marketplace_traffic_days")
