"""Capture the four-table learning prototype schema.

Revision ID: 20260722_0001
Revises:
Create Date: 2026-07-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260722_0001"
down_revision: str | None = None
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "books",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("subject", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_books_name", "books", ["name"], unique=True)

    op.create_table(
        "cards",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("chapter", sa.String(length=128), nullable=True),
        sa.Column("section", sa.String(length=128), nullable=True),
        sa.Column("card_type", sa.String(length=64), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("answer_points_json", sa.Text(), nullable=True),
        sa.Column("source_excerpt", sa.Text(), nullable=False),
        sa.Column("source_pages_json", sa.Text(), nullable=True),
        sa.Column("tags_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
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
        sa.ForeignKeyConstraint(["book_id"], ["books.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id", name="uq_cards_external_id"),
    )
    op.create_index("ix_cards_external_id", "cards", ["external_id"], unique=False)
    op.create_index("ix_cards_book_id", "cards", ["book_id"], unique=False)
    op.create_index("ix_cards_status", "cards", ["status"], unique=False)

    op.create_table(
        "review_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("card_id", sa.Integer(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stability", sa.Float(), nullable=False),
        sa.Column("difficulty", sa.Float(), nullable=False),
        sa.Column("elapsed_days", sa.Float(), nullable=False),
        sa.Column("scheduled_days", sa.Float(), nullable=False),
        sa.Column("reps", sa.Integer(), nullable=False),
        sa.Column("lapses", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("algorithm_version", sa.String(length=32), nullable=False),
        sa.Column("last_rating", sa.Integer(), nullable=True),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_review_states_card_id", "review_states", ["card_id"], unique=True)
    op.create_index("ix_review_states_due_at", "review_states", ["due_at"], unique=False)

    op.create_table(
        "review_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("card_id", sa.Integer(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("due_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stability_after", sa.Float(), nullable=True),
        sa.Column("difficulty_after", sa.Float(), nullable=True),
        sa.Column("algorithm_version", sa.String(length=32), nullable=False),
        sa.Column("state_before", sa.String(length=32), nullable=True),
        sa.Column("state_after", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_review_logs_card_id", "review_logs", ["card_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_review_logs_card_id", table_name="review_logs")
    op.drop_table("review_logs")
    op.drop_index("ix_review_states_due_at", table_name="review_states")
    op.drop_index("ix_review_states_card_id", table_name="review_states")
    op.drop_table("review_states")
    op.drop_index("ix_cards_status", table_name="cards")
    op.drop_index("ix_cards_book_id", table_name="cards")
    op.drop_index("ix_cards_external_id", table_name="cards")
    op.drop_table("cards")
    op.drop_index("ix_books_name", table_name="books")
    op.drop_table("books")
