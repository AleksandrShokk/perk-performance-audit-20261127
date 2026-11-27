"""WB regional snapshots and background demand loading; refresh Ozon cluster facts."""

import sqlalchemy as sa
from alembic import op

revision = "0031_supply_destinations"
down_revision = "0030_supply_plans"
branch_labels = depends_on = None


def upgrade():
    base = [
        sa.Column("workspace_id", sa.Uuid(), primary_key=True),
        sa.Column("store_id", sa.Uuid(), primary_key=True),
        sa.Column("product_key", sa.String(24), primary_key=True),
    ]
    op.create_table(
        "supply_destination_snapshots",
        *base,
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
    )
    op.create_table(
        "supply_destination_sync",
        sa.Column("workspace_id", sa.Uuid(), primary_key=True),
        sa.Column("store_id", sa.Uuid(), primary_key=True),
        sa.Column("product_key", sa.String(24), primary_key=True),
        sa.Column("requested_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("run_id", sa.Uuid()),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(64)),
        sa.ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "status IN ('pending','queued','running','ready','error')", name="status"
        ),
    )
    op.create_index("ix_supply_destination_due", "supply_destination_sync", ["next_attempt_at"])
    table = "supply_destination_snapshots"
    read = (
        "perk_store_access(workspace_id,store_id) "
        "AND perk_permission(workspace_id,'inventory.read')"
    )
    write = "perk_store_access(workspace_id,store_id) AND perk_is_member(workspace_id,'owner')"
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_read ON {table} FOR SELECT USING ({read})")
    op.execute(f"CREATE POLICY tenant_insert ON {table} FOR INSERT WITH CHECK ({write})")
    op.execute(
        f"CREATE POLICY tenant_update ON {table} FOR UPDATE USING ({write}) WITH CHECK ({write})"
    )
    # The outbox contains only routing metadata; workers reauthorize each job.
    op.execute(
        "UPDATE ozon_analytics_sync SET next_attempt_at=now() "
        "WHERE source='stock_cover' AND status IN ('ready','error')"
    )


def downgrade():
    op.drop_table("supply_destination_sync")
    op.drop_table("supply_destination_snapshots")
