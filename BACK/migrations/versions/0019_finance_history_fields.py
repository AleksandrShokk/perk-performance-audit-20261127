"""Remember the next bounded window of finance imports saved by an older loader."""

import sqlalchemy as sa
from alembic import op

revision = "0019_finance_history_fields"
down_revision = "0018_team_permissions"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("finance_projections", sa.Column("legacy_date_from", sa.Date(), nullable=True))
    op.add_column("finance_projections", sa.Column("legacy_date_to", sa.Date(), nullable=True))


def downgrade():
    op.drop_column("finance_projections", "legacy_date_to")
    op.drop_column("finance_projections", "legacy_date_from")
