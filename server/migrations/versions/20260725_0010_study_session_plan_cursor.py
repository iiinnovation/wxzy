"""bind study sessions to daily plans with cursor

Revision ID: 20260725_0010
Revises: 20260725_0009
Create Date: 2026-07-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260725_0010"
down_revision: str | None = "20260725_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("study_sessions") as batch_op:
        batch_op.add_column(sa.Column("daily_plan_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("plan_date", sa.String(length=10), nullable=True))
        batch_op.add_column(
            sa.Column(
                "cursor_position",
                sa.Integer(),
                server_default="0",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("active_started_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_study_sessions_daily_plan_id",
            "daily_plans",
            ["daily_plan_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_check_constraint(
            "ck_study_sessions_cursor_position",
            "cursor_position >= 0",
        )
        batch_op.create_unique_constraint(
            "uq_study_sessions_daily_plan_id",
            ["daily_plan_id"],
        )
        batch_op.create_index(
            "ix_study_sessions_daily_plan_id",
            ["daily_plan_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_study_sessions_user_plan_date",
            ["user_id", "plan_date"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("study_sessions") as batch_op:
        batch_op.drop_index("ix_study_sessions_user_plan_date")
        batch_op.drop_index("ix_study_sessions_daily_plan_id")
        batch_op.drop_constraint("uq_study_sessions_daily_plan_id", type_="unique")
        batch_op.drop_constraint("ck_study_sessions_cursor_position", type_="check")
        batch_op.drop_constraint("fk_study_sessions_daily_plan_id", type_="foreignkey")
        batch_op.drop_column("cursor_position")
        batch_op.drop_column("active_started_at")
        batch_op.drop_column("plan_date")
        batch_op.drop_column("daily_plan_id")
