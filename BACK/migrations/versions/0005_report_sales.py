"""Version encrypted aggregates that include historical report sales."""

import sqlalchemy as sa
from alembic import op

revision = "0005_report_sales"
down_revision = "0004_sync_plans_metrics"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "wb_metric_versions",
        sa.Column("format_version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade():
    op.drop_column("wb_metric_versions", "format_version")
