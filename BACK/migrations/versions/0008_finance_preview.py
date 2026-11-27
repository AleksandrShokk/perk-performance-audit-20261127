"""Track committed preview snapshots independently of task scheduling and retries."""

import sqlalchemy as sa
from alembic import op

revision = "0008_finance_preview"
down_revision = "0007_finance_projection"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sync_runs", sa.Column("preview_updated_at", sa.DateTime(timezone=True)))


def downgrade():
    op.drop_column("sync_runs", "preview_updated_at")
