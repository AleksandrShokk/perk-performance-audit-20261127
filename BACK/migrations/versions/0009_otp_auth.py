"""Open registration with one-time codes: email, Telegram and SMS factors.

Existing accounts were created from an invitation sent to their address, so their email
is treated as verified. The unused invitation table is removed.
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_otp_auth"
down_revision = "0008_finance_preview"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("phone", sa.String(16)))
    op.add_column("users", sa.Column("phone_verified_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("phone_channel", sa.String(16)))
    op.create_unique_constraint(op.f("uq_users_phone"), "users", ["phone"])
    op.create_check_constraint(
        op.f("ck_users_phone_channel"), "users", "phone_channel IN ('telegram', 'sms')"
    )
    op.execute("UPDATE users SET email_verified_at = created_at")

    op.add_column("auth_sessions", sa.Column("step_up_at", sa.DateTime(timezone=True)))
    op.add_column("auth_sessions", sa.Column("strong_step_up_at", sa.DateTime(timezone=True)))

    op.create_table(
        "otp_challenges",
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("destination_digest", sa.String(64), nullable=False),
        sa.Column("code_digest", sa.String(64), nullable=False),
        sa.Column("payload_ciphertext", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("sent_count", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "purpose IN ('register', 'login', 'step_up', 'phone_verify', 'password_reset')",
            name=op.f("ck_otp_challenges_purpose"),
        ),
        sa.CheckConstraint(
            "channel IN ('email', 'telegram', 'sms')", name=op.f("ck_otp_challenges_channel")
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND sent_count >= 1", name=op.f("ck_otp_challenges_counters")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_otp_challenges_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["auth_sessions.id"],
            name=op.f("fk_otp_challenges_session_id_auth_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_otp_challenges")),
    )
    op.create_index(op.f("ix_otp_challenges_user_id"), "otp_challenges", ["user_id"])
    op.create_index(op.f("ix_otp_challenges_session_id"), "otp_challenges", ["session_id"])
    op.create_index(
        op.f("ix_otp_challenges_destination_digest"), "otp_challenges", ["destination_digest"]
    )

    op.drop_table("invitations")


def downgrade():
    op.create_table(
        "invitations",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invitations")),
        sa.UniqueConstraint("token_digest", name=op.f("uq_invitations_token_digest")),
    )
    op.drop_table("otp_challenges")
    op.drop_column("auth_sessions", "strong_step_up_at")
    op.drop_column("auth_sessions", "step_up_at")
    op.drop_constraint(op.f("ck_users_phone_channel"), "users", type_="check")
    op.drop_constraint(op.f("uq_users_phone"), "users", type_="unique")
    op.drop_column("users", "phone_channel")
    op.drop_column("users", "phone_verified_at")
    op.drop_column("users", "phone")
    op.drop_column("users", "email_verified_at")
