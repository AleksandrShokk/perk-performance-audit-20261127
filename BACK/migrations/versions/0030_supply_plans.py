"""Encrypted internal supply plans, isolated by workspace and cabinet."""

import sqlalchemy as sa
from alembic import op

revision = "0030_supply_plans"
down_revision = "0029_supply_packaging"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "supply_plans",
        sa.Column("workspace_id", sa.Uuid(), primary_key=True),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint("revision >= 1", name="plan_revision"),
    )
    op.create_index("ix_supply_plans_store_id", "supply_plans", ["store_id"])
    op.create_index(
        "ix_supply_plans_workspace_updated", "supply_plans", ["workspace_id", "updated_at", "id"]
    )
    table = "supply_plans"
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
    op.drop_table("supply_plans")
