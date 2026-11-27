# ruff: noqa: E501
"""Scoped import diagnostics without provider payloads."""

import sqlalchemy as sa
from alembic import op

revision = "0038_import_issues"
down_revision = "0037_audit_history_requests"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "import_issues",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("record_key", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("workspace_id", "store_id", "source", "record_key"),
    )
    op.execute("ALTER TABLE import_issues ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE import_issues FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY scoped_issue ON import_issues FOR ALL "
        "USING(perk_store_access(workspace_id,store_id) AND perk_is_member(workspace_id,'owner')) "
        "WITH CHECK(perk_store_access(workspace_id,store_id) AND perk_is_member(workspace_id,'owner'))"
    )


def downgrade():
    op.drop_table("import_issues")
