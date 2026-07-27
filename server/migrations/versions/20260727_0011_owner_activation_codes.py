"""add one-time owner activation codes

Revision ID: 20260727_0011
Revises: 20260725_0010
Create Date: 2026-07-27

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260727_0011"
down_revision: str | None = "20260725_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "owner_activation_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash", name="uq_owner_activation_codes_code_hash"),
    )
    op.create_index(
        "ix_owner_activation_codes_user_id",
        "owner_activation_codes",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_owner_activation_codes_expires_at",
        "owner_activation_codes",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_owner_activation_codes_expires_at", table_name="owner_activation_codes")
    op.drop_index("ix_owner_activation_codes_user_id", table_name="owner_activation_codes")
    op.drop_table("owner_activation_codes")
