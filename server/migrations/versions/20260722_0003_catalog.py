"""add versioned document and card source catalog

Revision ID: 20260722_0003
Revises: 20260722_0002
Create Date: 2026-07-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260722_0003"
down_revision: str | None = "20260722_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_key", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("subject", sa.String(length=128), nullable=True),
        sa.Column("edition_note", sa.String(length=256), nullable=True),
        sa.Column(
            "copyright_scope", sa.String(length=32), server_default="personal_use", nullable=False
        ),
        sa.Column("copyright_notice", sa.String(length=512), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_key", name="uq_documents_document_key"),
    )
    op.create_index("ix_documents_document_key", "documents", ["document_key"], unique=False)
    op.create_index("ix_documents_subject", "documents", ["subject"], unique=False)

    op.create_table(
        "document_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_file_name", sa.String(length=256), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("processing_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="registered", nullable=False),
        sa.Column(
            "registered_at",
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
        sa.CheckConstraint("page_count > 0", name="ck_document_versions_page_count"),
        sa.CheckConstraint("length(source_sha256) = 64", name="ck_document_versions_sha256_length"),
        sa.CheckConstraint("size_bytes > 0", name="ck_document_versions_size_bytes"),
        sa.CheckConstraint(
            "status IN ('registered', 'split', 'parsing', 'parsed', 'cleaning', "
            "'structured', 'quality_review', 'needs_review', 'ready_for_generation', "
            "'published', 'failed', 'retrying')",
            name="ck_document_versions_status",
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id", "source_sha256", name="uq_document_versions_document_sha256"
        ),
    )
    op.create_index(
        "ix_document_versions_document_id", "document_versions", ["document_id"], unique=False
    )
    op.create_index("ix_document_versions_status", "document_versions", ["status"], unique=False)

    op.create_table(
        "chapters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_version_id", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("chapter_key", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("pdf_page_index_start", sa.Integer(), nullable=False),
        sa.Column("pdf_page_index_end", sa.Integer(), nullable=False),
        sa.Column("printed_page_start_label", sa.String(length=32), nullable=True),
        sa.Column("printed_page_end_label", sa.String(length=32), nullable=True),
        sa.Column("recognition_method", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_chapters_confidence",
        ),
        sa.CheckConstraint("level >= 0", name="ck_chapters_level"),
        sa.CheckConstraint(
            "pdf_page_index_end >= pdf_page_index_start", name="ck_chapters_pdf_page_range"
        ),
        sa.CheckConstraint("pdf_page_index_start >= 0", name="ck_chapters_pdf_page_start"),
        sa.CheckConstraint("sort_order >= 0", name="ck_chapters_sort_order"),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["parent_id"], ["chapters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_version_id", "chapter_key", name="uq_chapters_version_chapter_key"
        ),
    )
    op.create_index(
        "ix_chapters_document_version_id", "chapters", ["document_version_id"], unique=False
    )
    op.create_index("ix_chapters_parent_id", "chapters", ["parent_id"], unique=False)

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_version_id", sa.Integer(), nullable=False),
        sa.Column("chapter_id", sa.Integer(), nullable=True),
        sa.Column("chunk_key", sa.String(length=128), nullable=False),
        sa.Column("chapter_path", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("pdf_page_index_start", sa.Integer(), nullable=False),
        sa.Column("pdf_page_index_end", sa.Integer(), nullable=False),
        sa.Column("printed_page_labels", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("block_type", sa.String(length=64), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("cleaned_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("quality_status", sa.String(length=32), nullable=False),
        sa.Column("quality_flags", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("pipeline_version", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "pdf_page_index_end >= pdf_page_index_start",
            name="ck_document_chunks_pdf_page_range",
        ),
        sa.CheckConstraint("pdf_page_index_start >= 0", name="ck_document_chunks_pdf_page_start"),
        sa.CheckConstraint(
            "quality_status IN ('ready', 'needs_review', 'failed')",
            name="ck_document_chunks_quality_status",
        ),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapters.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_version_id", "chunk_key", name="uq_document_chunks_version_chunk_key"
        ),
    )
    op.create_index(
        "ix_document_chunks_chapter_id", "document_chunks", ["chapter_id"], unique=False
    )
    op.create_index(
        "ix_document_chunks_content_hash", "document_chunks", ["content_hash"], unique=False
    )
    op.create_index(
        "ix_document_chunks_document_version_id",
        "document_chunks",
        ["document_version_id"],
        unique=False,
    )
    op.create_index(
        "ix_document_chunks_quality_status", "document_chunks", ["quality_status"], unique=False
    )

    op.add_column(
        "cards", sa.Column("content_revision", sa.Integer(), server_default="1", nullable=False)
    )
    op.add_column("cards", sa.Column("content_hash", sa.String(length=64), nullable=True))
    op.add_column(
        "cards",
        sa.Column("answer_points", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
    )
    op.add_column(
        "cards", sa.Column("tags", sa.JSON(), server_default=sa.text("'[]'"), nullable=False)
    )
    op.create_index("ix_cards_content_hash", "cards", ["content_hash"], unique=False)

    op.create_table(
        "card_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("card_id", sa.Integer(), nullable=False),
        sa.Column("document_chunk_id", sa.Integer(), nullable=False),
        sa.Column("citation_order", sa.Integer(), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("pdf_page_index_start", sa.Integer(), nullable=False),
        sa.Column("pdf_page_index_end", sa.Integer(), nullable=False),
        sa.Column("printed_page_start_label", sa.String(length=32), nullable=True),
        sa.Column("printed_page_end_label", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("citation_order >= 0", name="ck_card_sources_citation_order"),
        sa.CheckConstraint(
            "pdf_page_index_end >= pdf_page_index_start", name="ck_card_sources_pdf_page_range"
        ),
        sa.CheckConstraint("pdf_page_index_start >= 0", name="ck_card_sources_pdf_page_start"),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_chunk_id"], ["document_chunks.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("card_id", "document_chunk_id", name="uq_card_sources_card_chunk"),
        sa.UniqueConstraint("card_id", "citation_order", name="uq_card_sources_card_order"),
    )
    op.create_index("ix_card_sources_card_id", "card_sources", ["card_id"], unique=False)
    op.create_index(
        "ix_card_sources_document_chunk_id", "card_sources", ["document_chunk_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_card_sources_document_chunk_id", table_name="card_sources")
    op.drop_index("ix_card_sources_card_id", table_name="card_sources")
    op.drop_table("card_sources")
    op.drop_index("ix_cards_content_hash", table_name="cards")
    op.drop_column("cards", "tags")
    op.drop_column("cards", "answer_points")
    op.drop_column("cards", "content_hash")
    op.drop_column("cards", "content_revision")
    op.drop_index("ix_document_chunks_quality_status", table_name="document_chunks")
    op.drop_index("ix_document_chunks_document_version_id", table_name="document_chunks")
    op.drop_index("ix_document_chunks_content_hash", table_name="document_chunks")
    op.drop_index("ix_document_chunks_chapter_id", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index("ix_chapters_parent_id", table_name="chapters")
    op.drop_index("ix_chapters_document_version_id", table_name="chapters")
    op.drop_table("chapters")
    op.drop_index("ix_document_versions_status", table_name="document_versions")
    op.drop_index("ix_document_versions_document_id", table_name="document_versions")
    op.drop_table("document_versions")
    op.drop_index("ix_documents_subject", table_name="documents")
    op.drop_index("ix_documents_document_key", table_name="documents")
    op.drop_table("documents")
