"""add publication import idempotency records

Revision ID: 20260725_0008
Revises: 20260723_0007
Create Date: 2026-07-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260725_0008"
down_revision: str | None = "20260723_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "publication_imports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("publication_id", sa.String(length=128), nullable=False),
        sa.Column("manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("package_hash", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("pipeline_version", sa.String(length=64), nullable=True),
        sa.Column("generation_version", sa.String(length=64), nullable=True),
        sa.Column("review_version", sa.String(length=64), nullable=True),
        sa.Column("counts", sa.JSON(), nullable=False),
        sa.Column("stats", sa.JSON(), nullable=False),
        sa.Column("conflicts", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('validated', 'imported', 'failed', 'conflict')",
            name="ck_publication_imports_status",
        ),
        sa.CheckConstraint(
            "length(manifest_hash) = 64",
            name="ck_publication_imports_manifest_hash",
        ),
        sa.CheckConstraint(
            "length(package_hash) = 64",
            name="ck_publication_imports_package_hash",
        ),
        sa.CheckConstraint(
            "schema_version >= 1",
            name="ck_publication_imports_schema_version",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("publication_id", name="uq_publication_imports_publication_id"),
    )
    op.create_index(
        "ix_publication_imports_publication_id",
        "publication_imports",
        ["publication_id"],
        unique=False,
    )
    op.create_index(
        "ix_publication_imports_manifest_hash",
        "publication_imports",
        ["manifest_hash"],
        unique=False,
    )
    op.create_index(
        "ix_publication_imports_status",
        "publication_imports",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_publication_imports_status", table_name="publication_imports")
    op.drop_index("ix_publication_imports_manifest_hash", table_name="publication_imports")
    op.drop_index("ix_publication_imports_publication_id", table_name="publication_imports")
    op.drop_table("publication_imports")
