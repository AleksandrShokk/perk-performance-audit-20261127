"""Neutral variant costs and explicit physical FBS warehouse semantics."""

import sqlalchemy as sa
from alembic import op

revision = "0027_ozon_costs_inventory"
down_revision = "0026_ozon_finance"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "inventory_settings",
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("fbs_mode", sa.String(16), nullable=False),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("fbs_mode IN ('separate','shared')", name="fbs_mode"),
    )
    op.create_table(
        "marketplace_variant_costs",
        sa.Column("workspace_id", sa.Uuid(), primary_key=True),
        sa.Column("store_id", sa.Uuid(), primary_key=True),
        sa.Column("variant_id", sa.Uuid(), primary_key=True),
        sa.Column("currency", sa.String(3), primary_key=True),
        sa.Column("effective_from", sa.Date(), primary_key=True),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
    )
    for table, reader, writer in [
        (
            "inventory_settings",
            "perk_permission(workspace_id,'inventory.read')",
            "perk_is_member(workspace_id,'owner')",
        ),
        (
            "marketplace_variant_costs",
            (
                "perk_store_access(workspace_id,store_id) "
                "AND perk_permission(workspace_id,'profit.read')"
            ),
            (
                "perk_store_access(workspace_id,store_id) "
                "AND perk_permission(workspace_id,'costs.write')"
            ),
        ),
    ]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_read ON {table} FOR SELECT USING ({reader})")
        op.execute(f"CREATE POLICY tenant_insert ON {table} FOR INSERT WITH CHECK ({writer})")
        op.execute(
            f"CREATE POLICY tenant_update ON {table} FOR UPDATE "
            f"USING ({writer}) WITH CHECK ({writer})"
        )
    op.execute("DROP POLICY tenant_read ON marketplace_realizations")
    op.execute("""CREATE POLICY tenant_read ON marketplace_realizations FOR SELECT USING (
        perk_store_access(workspace_id,store_id) AND
        (perk_permission(workspace_id,'analytics.read') OR
         perk_permission(workspace_id,'profit.read')))""")
    # Rebuild only Ozon finance facts with signed product quantities. No report data is cleared.
    op.execute("""UPDATE ozon_analytics_sync SET status='pending',run_id=NULL,next_attempt_at=now(),
        updated_at=NULL,cursor=(now() AT TIME ZONE 'Europe/Moscow')::date-1 WHERE source='finance'
        """)


def downgrade():
    op.execute("DROP POLICY tenant_read ON marketplace_realizations")
    op.execute("""CREATE POLICY tenant_read ON marketplace_realizations FOR SELECT USING (
        perk_store_access(workspace_id,store_id) AND
        perk_permission(workspace_id,'analytics.read'))""")
    op.drop_table("marketplace_variant_costs")
    op.drop_table("inventory_settings")
