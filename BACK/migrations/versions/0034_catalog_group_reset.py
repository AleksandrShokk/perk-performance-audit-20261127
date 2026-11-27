"""Allow owners/admins to restore native groups; employees still cannot change grouping."""

from alembic import op

revision = "0034_catalog_group_reset"
down_revision = "0033_coverage_channels"
branch_labels = depends_on = None


def upgrade():
    op.execute("""CREATE POLICY tenant_delete ON catalog_overrides FOR DELETE
        USING (perk_store_access(workspace_id,store_id)
        AND perk_is_member(workspace_id,'owner'))""")


def downgrade():
    op.execute("DROP POLICY tenant_delete ON catalog_overrides")
