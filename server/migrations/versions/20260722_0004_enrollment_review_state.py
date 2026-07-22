"""add personal card enrollment and review state

Revision ID: 20260722_0004
Revises: 20260722_0003
Create Date: 2026-07-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260722_0004"
down_revision: str | None = "20260722_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "card_enrollments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("card_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("priority", sa.Integer(), server_default="50", nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("introduced_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("priority BETWEEN 0 AND 100", name="ck_card_enrollments_priority"),
        sa.CheckConstraint(
            "source IN ('manual', 'chapter', 'plan')", name="ck_card_enrollments_source"
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'active', 'suspended', 'retired')",
            name="ck_card_enrollments_status",
        ),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "card_id", name="uq_card_enrollments_user_card"),
    )
    op.create_index("ix_card_enrollments_card_id", "card_enrollments", ["card_id"], unique=False)
    op.create_index("ix_card_enrollments_status", "card_enrollments", ["status"], unique=False)
    op.create_index("ix_card_enrollments_user_id", "card_enrollments", ["user_id"], unique=False)

    op.create_table(
        "card_review_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("card_id", sa.Integer(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stability", sa.Float(), server_default="1.0", nullable=False),
        sa.Column("difficulty", sa.Float(), server_default="5.0", nullable=False),
        sa.Column("elapsed_days", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("scheduled_days", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("reps", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lapses", sa.Integer(), server_default="0", nullable=False),
        sa.Column("state", sa.String(length=16), server_default="new", nullable=False),
        sa.Column("algorithm_version", sa.String(length=32), nullable=False),
        sa.Column("last_rating", sa.Integer(), nullable=True),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True),
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
            "difficulty >= 1 AND difficulty <= 10", name="ck_card_review_states_difficulty"
        ),
        sa.CheckConstraint("elapsed_days >= 0", name="ck_card_review_states_elapsed_days"),
        sa.CheckConstraint("lapses >= 0", name="ck_card_review_states_lapses"),
        sa.CheckConstraint(
            "last_rating IS NULL OR last_rating BETWEEN 1 AND 4",
            name="ck_card_review_states_last_rating",
        ),
        sa.CheckConstraint("reps >= 0", name="ck_card_review_states_reps"),
        sa.CheckConstraint("scheduled_days >= 0", name="ck_card_review_states_scheduled_days"),
        sa.CheckConstraint("stability >= 0", name="ck_card_review_states_stability"),
        sa.CheckConstraint(
            "state IN ('new', 'learning', 'review', 'relearning')",
            name="ck_card_review_states_state",
        ),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "card_id", name="uq_card_review_states_user_card"),
    )
    op.create_index(
        "ix_card_review_states_card_id", "card_review_states", ["card_id"], unique=False
    )
    op.create_index("ix_card_review_states_due_at", "card_review_states", ["due_at"], unique=False)
    op.create_index(
        "ix_card_review_states_user_id", "card_review_states", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_card_review_states_user_id", table_name="card_review_states")
    op.drop_index("ix_card_review_states_due_at", table_name="card_review_states")
    op.drop_index("ix_card_review_states_card_id", table_name="card_review_states")
    op.drop_table("card_review_states")
    op.drop_index("ix_card_enrollments_user_id", table_name="card_enrollments")
    op.drop_index("ix_card_enrollments_status", table_name="card_enrollments")
    op.drop_index("ix_card_enrollments_card_id", table_name="card_enrollments")
    op.drop_table("card_enrollments")
