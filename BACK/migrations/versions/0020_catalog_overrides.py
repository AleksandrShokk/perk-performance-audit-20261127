"""Explicit model groups, independent of WB/Ozon regrouping and financial identifiers."""

import sqlalchemy as sa
from alembic import op

revision = "0020_catalog_overrides"
down_revision = "0019_finance_history_fields"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "catalog_overrides",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("nm_id", sa.String(32), nullable=False),
        sa.Column("model_key", sa.String(96), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("workspace_id", "store_id", "nm_id"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
    )
    op.execute("ALTER TABLE catalog_overrides ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE catalog_overrides FORCE ROW LEVEL SECURITY")
    read = (
        "perk_store_access(workspace_id,store_id) AND "
        "(perk_permission(workspace_id,'inventory.read') OR "
        "perk_permission(workspace_id,'profit.read'))"
    )
    writer = "perk_store_access(workspace_id,store_id) AND perk_is_member(workspace_id,'owner')"
    op.execute(f"CREATE POLICY tenant_read ON catalog_overrides FOR SELECT USING ({read})")
    op.execute(f"CREATE POLICY tenant_insert ON catalog_overrides FOR INSERT WITH CHECK ({writer})")
    op.execute(
        f"CREATE POLICY tenant_update ON catalog_overrides FOR UPDATE "
        f"USING ({writer}) WITH CHECK ({writer})"
    )


def downgrade():
    op.drop_table("catalog_overrides")
