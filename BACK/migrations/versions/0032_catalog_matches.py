"""Explicit marketplace correspondences and reviewed catalog file imports."""

import sqlalchemy as sa
from alembic import op

revision = "0032_catalog_matches"
down_revision = "0031_supply_destinations"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "catalog_product_matches",
        sa.Column("workspace_id", sa.Uuid(), primary_key=True),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("left_store_id", sa.Uuid(), nullable=False),
        sa.Column("right_store_id", sa.Uuid(), nullable=False),
        sa.Column("left_variant_id", sa.Uuid(), nullable=False),
        sa.Column("right_variant_id", sa.Uuid(), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "left_store_id"],
            ["stores.workspace_id", "stores.id"],
            name="fk_catalog_matches_left_store",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "right_store_id"],
            ["stores.workspace_id", "stores.id"],
            name="fk_catalog_matches_right_store",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "left_store_id",
            "left_variant_id",
            "right_store_id",
            name="uq_catalog_match_left",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "right_store_id",
            "right_variant_id",
            "left_store_id",
            name="uq_catalog_match_right",
        ),
    )
    op.create_table(
        "catalog_import_previews",
        sa.Column("workspace_id", sa.Uuid(), primary_key=True),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["workspace_id", "store_id"],
            ["stores.workspace_id", "stores.id"],
            ondelete="CASCADE",
        ),
    )
    for table, access in [
        (
            "catalog_product_matches",
            (
                "perk_store_access(workspace_id,left_store_id) "
                "AND perk_store_access(workspace_id,right_store_id)"
            ),
        ),
        (
            "catalog_import_previews",
            "perk_store_access(workspace_id,store_id) AND created_by=perk_actor()",
        ),
    ]:
        allowed = access + " AND perk_is_member(workspace_id,'owner')"
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_read ON {table} FOR SELECT USING ({allowed})")
        op.execute(f"CREATE POLICY tenant_insert ON {table} FOR INSERT WITH CHECK ({allowed})")
        op.execute(
            f"CREATE POLICY tenant_update ON {table} FOR UPDATE "
            f"USING ({allowed}) WITH CHECK ({allowed})"
        )
        op.execute(f"CREATE POLICY tenant_delete ON {table} FOR DELETE USING ({allowed})")
    # Old WB region aggregates do not have warehouse-level demand. Re-read them
    # using the same bounded queue and seller-wide quota; do not invent a split.
    op.execute(
        "UPDATE supply_destination_sync SET status='pending',run_id=NULL,next_attempt_at=now() "
        "WHERE status IN ('ready','error')"
    )


def downgrade():
    op.drop_table("catalog_import_previews")
    op.drop_table("catalog_product_matches")
