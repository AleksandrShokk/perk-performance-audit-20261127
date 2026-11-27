"""Persistent per-cabinet packaging for neutral replenishment reports."""

import sqlalchemy as sa
from alembic import op

revision = "0029_supply_packaging"
down_revision = "0028_ozon_parity"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "supply_packaging",
        sa.Column("workspace_id", sa.Uuid(), primary_key=True),
        sa.Column("store_id", sa.Uuid(), primary_key=True),
        sa.Column("product_key", sa.String(100), primary_key=True),
        sa.Column("box_multiple", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint("box_multiple BETWEEN 1 AND 10000", name="box_multiple"),
    )
    table = "supply_packaging"
    reader = (
        "perk_store_access(workspace_id,store_id) "
        "AND perk_permission(workspace_id,'inventory.read')"
    )
    writer = "perk_store_access(workspace_id,store_id) AND perk_is_member(workspace_id,'owner')"
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_read ON {table} FOR SELECT USING ({reader})")
    op.execute(f"CREATE POLICY tenant_insert ON {table} FOR INSERT WITH CHECK ({writer})")
    op.execute(
        f"CREATE POLICY tenant_update ON {table} FOR UPDATE USING ({writer}) WITH CHECK ({writer})"
    )
    op.execute(f"CREATE POLICY tenant_delete ON {table} FOR DELETE USING ({writer})")


def downgrade():
    op.drop_table("supply_packaging")
