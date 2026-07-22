"""add single-owner identity and learning profile

Revision ID: 20260722_0002
Revises: 20260722_0001
Create Date: 2026-07-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260722_0002"
down_revision: str | None = "20260722_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("wechat_openid_hash", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("display_name", sa.String(length=64), nullable=True),
        sa.Column("timezone", sa.String(length=64), server_default="Asia/Shanghai", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_users_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("wechat_openid_hash", name="uq_users_wechat_openid_hash"),
    )
    op.create_index(
        "uq_users_single_active_owner",
        "users",
        ["status"],
        unique=True,
        sqlite_where=sa.text("status = 'active'"),
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "learning_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "goal_type", sa.String(length=32), server_default="daily_learning", nullable=False
        ),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("daily_minutes", sa.Integer(), server_default="20", nullable=False),
        sa.Column(
            "study_days",
            sa.JSON(),
            server_default=sa.text("'[true,true,true,true,true,true,true]'"),
            nullable=False,
        ),
        sa.Column("desired_retention", sa.Float(), server_default="0.90", nullable=False),
        sa.Column("new_card_ceiling", sa.Integer(), server_default="5", nullable=False),
        sa.Column("subject_priorities", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column(
            "initial_self_assessment",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "daily_minutes BETWEEN 5 AND 240", name="ck_learning_profiles_daily_minutes"
        ),
        sa.CheckConstraint(
            "desired_retention BETWEEN 0.70 AND 0.99",
            name="ck_learning_profiles_desired_retention",
        ),
        sa.CheckConstraint(
            "goal_type IN ('daily_learning', 'exam', 'focused')",
            name="ck_learning_profiles_goal_type",
        ),
        sa.CheckConstraint(
            "new_card_ceiling BETWEEN 0 AND 100",
            name="ck_learning_profiles_new_card_ceiling",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_learning_profiles_user_id"),
    )

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("device_label", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_user_sessions_token_hash"),
    )
    op.create_index("ix_user_sessions_expires_at", "user_sessions", ["expires_at"], unique=False)
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_index("ix_user_sessions_expires_at", table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_table("learning_profiles")
    op.drop_index("uq_users_single_active_owner", table_name="users")
    op.drop_table("users")
