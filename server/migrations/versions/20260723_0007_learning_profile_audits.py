"""add learning profile audit log

Revision ID: 20260723_0007
Revises: 20260723_0006
Create Date: 2026-07-23

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260723_0007"
down_revision: str | None = "20260723_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "learning_profile_audits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("changed_fields", sa.JSON(), nullable=False),
        sa.Column("before_values", sa.JSON(), nullable=False),
        sa.Column("after_values", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["profile_id"], ["learning_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_learning_profile_audits_user_id",
        "learning_profile_audits",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_learning_profile_audits_profile_id",
        "learning_profile_audits",
        ["profile_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_learning_profile_audits_profile_id", table_name="learning_profile_audits")
    op.drop_index("ix_learning_profile_audits_user_id", table_name="learning_profile_audits")
    op.drop_table("learning_profile_audits")
