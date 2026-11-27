"""Encrypted daily finance facts for fast, versioned profit calculations."""

import sqlalchemy as sa
from alembic import op

revision = "0007_finance_projection"
down_revision = "0006_cost_inputs"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("finance_days", "finance_projections"):
        columns = [
            sa.Column("workspace_id", sa.Uuid(), nullable=False),
            sa.Column("store_id", sa.Uuid(), nullable=False),
            sa.ForeignKeyConstraint(
                ["workspace_id", "store_id"],
                ["stores.workspace_id", "stores.id"],
                ondelete="CASCADE",
            ),
        ]
        keys = ["workspace_id", "store_id"]
        if table == "finance_days":
            columns += [
                sa.Column("day", sa.Date(), nullable=False),
                sa.Column("currency", sa.String(16), nullable=False),
                sa.Column("ciphertext", sa.Text(), nullable=False),
            ]
            keys += ["day", "currency"]
        else:
            columns += [
                sa.Column("source_run_id", sa.Uuid(), nullable=False),
                sa.Column("format_version", sa.Integer(), nullable=False),
                sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            ]
        op.create_table(table, *columns, sa.PrimaryKeyConstraint(*keys))
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        member = (
            f"EXISTS (SELECT 1 FROM memberships m WHERE m.workspace_id = {table}.workspace_id "
            "AND m.user_id = NULLIF(current_setting('perk.user_id', true), '')::uuid)"
        )
        owner = member[:-1] + " AND m.role = 'owner')"
        op.execute(f"CREATE POLICY tenant_read ON {table} FOR SELECT USING ({member})")
        op.execute(f"CREATE POLICY tenant_insert ON {table} FOR INSERT WITH CHECK ({owner})")
        op.execute(
            f"CREATE POLICY tenant_update ON {table} FOR UPDATE "
            f"USING ({owner}) WITH CHECK ({owner})"
        )
        op.execute(f"CREATE POLICY tenant_delete ON {table} FOR DELETE USING ({owner})")


def downgrade():
    op.drop_table("finance_projections")
    op.drop_table("finance_days")
