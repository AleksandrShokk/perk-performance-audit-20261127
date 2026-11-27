"""Encrypted cost history, bounded previews and external store expenses."""

import sqlalchemy as sa
from alembic import op

revision = "0006_cost_inputs"
down_revision = "0005_report_sales"
branch_labels = None
depends_on = None


def upgrade():
    def tenant_columns():
        return [
            sa.Column("workspace_id", sa.Uuid(), nullable=False),
            sa.Column("store_id", sa.Uuid(), nullable=False),
        ]

    def common():
        return [
            sa.Column("ciphertext", sa.Text(), nullable=False),
            sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.ForeignKeyConstraint(
                ["workspace_id", "store_id"],
                ["stores.workspace_id", "stores.id"],
                ondelete="CASCADE",
            ),
        ]

    op.create_table(
        "product_costs",
        *tenant_columns(),
        sa.Column("nm_id", sa.String(32), nullable=False),
        sa.Column("barcode", sa.String(100), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        *common(),
        sa.PrimaryKeyConstraint(
            "workspace_id", "store_id", "nm_id", "barcode", "currency", "effective_from"
        ),
    )
    op.create_table(
        "cost_imports",
        *tenant_columns(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        *common(),
        sa.PrimaryKeyConstraint("workspace_id", "store_id", "id"),
    )
    op.create_table(
        "external_expenses",
        *tenant_columns(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        *common(),
        sa.PrimaryKeyConstraint("workspace_id", "store_id", "id"),
    )
    for table in ("product_costs", "cost_imports", "external_expenses"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        member = (
            f"EXISTS (SELECT 1 FROM memberships m WHERE m.workspace_id = {table}.workspace_id "
            "AND m.user_id = NULLIF(current_setting('perk.user_id', true), '')::uuid)"
        )
        owner = member[:-1] + " AND m.role = 'owner')"
        op.execute(f"CREATE POLICY tenant_read ON {table} FOR SELECT USING ({member})")
        op.execute(f"CREATE POLICY tenant_insert ON {table} FOR INSERT WITH CHECK ({owner})")
        if table != "product_costs":
            op.execute(
                f"CREATE POLICY tenant_update ON {table} FOR UPDATE "
                f"USING ({owner}) WITH CHECK ({owner})"
            )
        if table == "cost_imports":
            op.execute(f"CREATE POLICY tenant_delete ON {table} FOR DELETE USING ({owner})")


def downgrade():
    for table in ("external_expenses", "cost_imports", "product_costs"):
        op.drop_table(table)
