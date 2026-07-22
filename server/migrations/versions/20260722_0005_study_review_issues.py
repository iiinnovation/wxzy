"""add study sessions, review attempts and card issues

Revision ID: 20260722_0005
Revises: 20260722_0004
Create Date: 2026-07-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260722_0005"
down_revision: str | None = "20260722_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "study_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("session_type", sa.String(length=16), server_default="daily", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="planned", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("estimated_minutes", sa.Integer(), server_default="20", nullable=False),
        sa.Column("actual_minutes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("planned_task_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completed_task_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("interruption_reason", sa.String(length=512), nullable=True),
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
            "session_type IN ('daily', 'focused', 'review', 'onboarding')",
            name="ck_study_sessions_type",
        ),
        sa.CheckConstraint(
            "status IN ('planned', 'active', 'completed', 'interrupted', 'cancelled')",
            name="ck_study_sessions_status",
        ),
        sa.CheckConstraint(
            "estimated_minutes BETWEEN 0 AND 1440", name="ck_study_sessions_estimated"
        ),
        sa.CheckConstraint("actual_minutes BETWEEN 0 AND 1440", name="ck_study_sessions_actual"),
        sa.CheckConstraint("planned_task_count >= 0", name="ck_study_sessions_planned_tasks"),
        sa.CheckConstraint("completed_task_count >= 0", name="ck_study_sessions_completed_tasks"),
        sa.CheckConstraint(
            "completed_task_count <= planned_task_count",
            name="ck_study_sessions_completed_le_planned",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_study_sessions_user_id", "study_sessions", ["user_id"], unique=False)
    op.create_index("ix_study_sessions_status", "study_sessions", ["status"], unique=False)
    op.create_index(
        "ix_study_sessions_user_status", "study_sessions", ["user_id", "status"], unique=False
    )

    op.create_table(
        "review_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("card_id", sa.Integer(), nullable=False),
        sa.Column("card_revision", sa.Integer(), nullable=False),
        sa.Column("client_attempt_id", sa.String(length=128), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("response_ms", sa.Integer(), nullable=False),
        sa.Column("hint_used", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("reveal_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("answer_payload", sa.JSON(), nullable=True),
        sa.Column("state_before", sa.JSON(), nullable=False),
        sa.Column("state_after", sa.JSON(), nullable=False),
        sa.Column("due_before", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("algorithm_version", sa.String(length=32), nullable=False),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("card_revision > 0", name="ck_review_attempts_card_revision"),
        sa.CheckConstraint("rating BETWEEN 1 AND 4", name="ck_review_attempts_rating"),
        sa.CheckConstraint(
            "response_ms BETWEEN 0 AND 86400000", name="ck_review_attempts_response_ms"
        ),
        sa.CheckConstraint(
            "reveal_count BETWEEN 0 AND 100", name="ck_review_attempts_reveal_count"
        ),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["session_id"], ["study_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "client_attempt_id", name="uq_review_attempts_user_client_id"
        ),
    )
    op.create_index(
        "ix_review_attempts_session_id", "review_attempts", ["session_id"], unique=False
    )
    op.create_index("ix_review_attempts_user_id", "review_attempts", ["user_id"], unique=False)
    op.create_index("ix_review_attempts_card_id", "review_attempts", ["card_id"], unique=False)
    op.create_index(
        "ix_review_attempts_user_card", "review_attempts", ["user_id", "card_id"], unique=False
    )

    op.create_table(
        "card_issues",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("card_id", sa.Integer(), nullable=False),
        sa.Column("card_revision", sa.Integer(), nullable=False),
        sa.Column("issue_type", sa.String(length=32), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "issue_type IN ('fact_error', 'source_error', 'too_large', 'too_difficult', "
            "'unclear', 'concept_confusion')",
            name="ck_card_issues_type",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'in_review', 'resolved', 'dismissed')",
            name="ck_card_issues_status",
        ),
        sa.CheckConstraint("card_revision > 0", name="ck_card_issues_card_revision"),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_card_issues_user_id", "card_issues", ["user_id"], unique=False)
    op.create_index("ix_card_issues_card_id", "card_issues", ["card_id"], unique=False)
    op.create_index(
        "ix_card_issues_user_status", "card_issues", ["user_id", "status"], unique=False
    )
    op.create_index(
        "ix_card_issues_card_status", "card_issues", ["card_id", "status"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_card_issues_card_status", table_name="card_issues")
    op.drop_index("ix_card_issues_user_status", table_name="card_issues")
    op.drop_index("ix_card_issues_card_id", table_name="card_issues")
    op.drop_index("ix_card_issues_user_id", table_name="card_issues")
    op.drop_table("card_issues")
    op.drop_index("ix_review_attempts_user_card", table_name="review_attempts")
    op.drop_index("ix_review_attempts_card_id", table_name="review_attempts")
    op.drop_index("ix_review_attempts_user_id", table_name="review_attempts")
    op.drop_index("ix_review_attempts_session_id", table_name="review_attempts")
    op.drop_table("review_attempts")
    op.drop_index("ix_study_sessions_user_status", table_name="study_sessions")
    op.drop_index("ix_study_sessions_status", table_name="study_sessions")
    op.drop_index("ix_study_sessions_user_id", table_name="study_sessions")
    op.drop_table("study_sessions")
