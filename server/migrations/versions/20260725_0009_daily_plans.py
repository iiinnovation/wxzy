"""add daily plans and plan items

Revision ID: 20260725_0009
Revises: 20260725_0008
Create Date: 2026-07-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260725_0009"
down_revision: str | None = "20260725_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("plan_date", sa.String(length=10), nullable=False),
        sa.Column("budget_minutes", sa.Integer(), nullable=False),
        sa.Column("adjusted_budget_minutes", sa.Integer(), nullable=True),
        sa.Column("estimated_minutes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("due_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("new_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("weak_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("generation_version", sa.String(length=32), nullable=False),
        sa.Column("is_initial", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("forecast_minutes_7d", sa.Integer(), server_default="0", nullable=False),
        sa.Column("forecast_budget_7d", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "new_cards_paused", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("pause_reasons", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("plan_reasons", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
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
            "budget_minutes BETWEEN 5 AND 240", name="ck_daily_plans_budget_minutes"
        ),
        sa.CheckConstraint(
            "adjusted_budget_minutes IS NULL OR (adjusted_budget_minutes BETWEEN 5 AND 240)",
            name="ck_daily_plans_adjusted_budget_minutes",
        ),
        sa.CheckConstraint(
            "estimated_minutes BETWEEN 0 AND 1440", name="ck_daily_plans_estimated_minutes"
        ),
        sa.CheckConstraint("due_count >= 0", name="ck_daily_plans_due_count"),
        sa.CheckConstraint("new_count >= 0", name="ck_daily_plans_new_count"),
        sa.CheckConstraint("weak_count >= 0", name="ck_daily_plans_weak_count"),
        sa.CheckConstraint("forecast_minutes_7d >= 0", name="ck_daily_plans_forecast_minutes_7d"),
        sa.CheckConstraint("forecast_budget_7d >= 0", name="ck_daily_plans_forecast_budget_7d"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "plan_date", name="uq_daily_plans_user_date"),
    )
    op.create_index("ix_daily_plans_user_id", "daily_plans", ["user_id"], unique=False)
    op.create_index(
        "ix_daily_plans_user_date", "daily_plans", ["user_id", "plan_date"], unique=False
    )

    op.create_table(
        "daily_plan_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("item_type", sa.String(length=16), nullable=False),
        sa.Column("enrollment_id", sa.Integer(), nullable=False),
        sa.Column("card_id", sa.Integer(), nullable=False),
        sa.Column("estimated_seconds", sa.Integer(), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("reason_detail", sa.String(length=512), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "item_type IN ('due', 'overdue', 'new', 'weak_topic', 'repair', 'mixed_weekly')",
            name="ck_daily_plan_items_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'skipped')",
            name="ck_daily_plan_items_status",
        ),
        sa.CheckConstraint(
            "estimated_seconds BETWEEN 1 AND 3600",
            name="ck_daily_plan_items_estimated_seconds",
        ),
        sa.CheckConstraint("position >= 0", name="ck_daily_plan_items_position"),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["enrollment_id"], ["card_enrollments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["plan_id"], ["daily_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "position", name="uq_daily_plan_items_plan_position"),
        sa.UniqueConstraint("plan_id", "card_id", name="uq_daily_plan_items_plan_card"),
    )
    op.create_index("ix_daily_plan_items_plan_id", "daily_plan_items", ["plan_id"], unique=False)
    op.create_index(
        "ix_daily_plan_items_enrollment_id",
        "daily_plan_items",
        ["enrollment_id"],
        unique=False,
    )
    op.create_index("ix_daily_plan_items_card_id", "daily_plan_items", ["card_id"], unique=False)
    op.create_index("ix_daily_plan_items_status", "daily_plan_items", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_daily_plan_items_status", table_name="daily_plan_items")
    op.drop_index("ix_daily_plan_items_card_id", table_name="daily_plan_items")
    op.drop_index("ix_daily_plan_items_enrollment_id", table_name="daily_plan_items")
    op.drop_index("ix_daily_plan_items_plan_id", table_name="daily_plan_items")
    op.drop_table("daily_plan_items")
    op.drop_index("ix_daily_plans_user_date", table_name="daily_plans")
    op.drop_index("ix_daily_plans_user_id", table_name="daily_plans")
    op.drop_table("daily_plans")
