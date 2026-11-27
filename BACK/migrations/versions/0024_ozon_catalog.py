"""Ozon catalog snapshots; metadata-only, reauthorized worker outbox."""

import sqlalchemy as sa
from alembic import op

revision = "0024_ozon_catalog"
down_revision = "0023_mobile_supplies"
branch_labels = depends_on = None


def upgrade():
    for name in ("marketplace_catalog_snapshots", "ozon_catalog_sync"):
        columns = (
            [
                sa.Column("ciphertext", sa.Text(), nullable=False),
                sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            ]
            if name == "marketplace_catalog_snapshots"
            else [
                sa.Column("requested_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
                sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
                sa.Column("run_id", sa.Uuid()),
                sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
                sa.Column("updated_at", sa.DateTime(timezone=True)),
                sa.Column("records_processed", sa.Integer(), nullable=False, server_default="0"),
                sa.Column("error_code", sa.String(64)),
                sa.CheckConstraint(
                    "status IN ('pending','queued','running','ready','error')", name="status"
                ),
            ]
        )
        op.create_table(
            name,
            sa.Column("workspace_id", sa.Uuid(), nullable=False),
            sa.Column("store_id", sa.Uuid(), nullable=False),
            *columns,
            sa.PrimaryKeyConstraint("workspace_id", "store_id"),
            sa.ForeignKeyConstraint(
                ["workspace_id", "store_id"],
                ["stores.workspace_id", "stores.id"],
                ondelete="CASCADE",
            ),
        )
    # Same outbox pattern as sync_schedules: identifiers/status only, never exposed by API.
    op.create_index("ix_ozon_catalog_due", "ozon_catalog_sync", ["next_attempt_at"])
    table = "marketplace_catalog_snapshots"
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    scope = "perk_store_access(workspace_id,store_id)"
    read = (
        scope + " AND (perk_permission(workspace_id,'inventory.read') "
        "OR perk_permission(workspace_id,'profit.read'))"
    )
    writer = scope + " AND perk_is_member(workspace_id,'owner')"
    op.execute(f"CREATE POLICY tenant_read ON {table} FOR SELECT USING ({read})")
    op.execute(f"CREATE POLICY tenant_insert ON {table} FOR INSERT WITH CHECK ({writer})")
    op.execute(
        f"CREATE POLICY tenant_update ON {table} FOR UPDATE USING ({writer}) WITH CHECK ({writer})"
    )
    # Existing verified Ozon connections start automatically after deployment.
    op.execute("""INSERT INTO ozon_catalog_sync
        (workspace_id,store_id,requested_by,status,next_attempt_at,records_processed)
        SELECT DISTINCT ON (s.id) s.workspace_id,s.id,m.user_id,'pending',now(),0
        FROM stores s JOIN memberships m ON m.workspace_id=s.workspace_id
        JOIN users u ON u.id=m.user_id
        WHERE s.marketplace='ozon' AND s.is_active AND s.connection_status='connected'
        AND m.role IN ('owner','admin') AND u.is_active AND u.email_verified_at IS NOT NULL
        ORDER BY s.id,CASE m.role WHEN 'owner' THEN 0 ELSE 1 END,m.user_id
        ON CONFLICT DO NOTHING""")


def downgrade():
    op.drop_table("ozon_catalog_sync")
    op.drop_table("marketplace_catalog_snapshots")
