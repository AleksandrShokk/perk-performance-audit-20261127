"""Separate OTP purpose for old-phone/email verification before phone replacement."""

from alembic import op

revision = "0043_phone_change"
down_revision = "0042_smart_notifications"
branch_labels = None
depends_on = None


def constraint(purposes):
    op.drop_constraint(op.f("ck_otp_challenges_purpose"), "otp_challenges", type_="check")
    op.create_check_constraint(
        op.f("ck_otp_challenges_purpose"), "otp_challenges", f"purpose IN ({purposes})"
    )


def upgrade():
    constraint("'register', 'login', 'step_up', 'phone_verify', 'phone_change', 'password_reset'")


def downgrade():
    # Only transient replacement challenges are removed; accounts remain intact.
    op.execute("DELETE FROM otp_challenges WHERE purpose='phone_change'")
    constraint("'register', 'login', 'step_up', 'phone_verify', 'password_reset'")
