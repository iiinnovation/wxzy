from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.types import UTCDateTime
from ..db import Base

if TYPE_CHECKING:
    from ..models import ReviewState


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("document_key", name="uq_documents_document_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    edition_note: Mapped[str | None] = mapped_column(String(256), nullable=True)
    copyright_scope: Mapped[str] = mapped_column(
        String(32), default="personal_use", server_default="personal_use"
    )
    copyright_notice: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now()
    )

    versions: Mapped[list[DocumentVersion]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "source_sha256", name="uq_document_versions_document_sha256"
        ),
        CheckConstraint("length(source_sha256) = 64", name="ck_document_versions_sha256_length"),
        CheckConstraint("page_count > 0", name="ck_document_versions_page_count"),
        CheckConstraint("size_bytes > 0", name="ck_document_versions_size_bytes"),
        CheckConstraint(
            "status IN ('registered', 'split', 'parsing', 'parsed', 'cleaning', "
            "'structured', 'quality_review', 'needs_review', 'ready_for_generation', "
            "'published', 'failed', 'retrying')",
            name="ck_document_versions_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_name: Mapped[str] = mapped_column(String(256), nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    processing_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="registered", server_default="registered", index=True
    )
    registered_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now()
    )

    document: Mapped[Document] = relationship(back_populates="versions")
    chapters: Mapped[list[Chapter]] = relationship(
        back_populates="document_version", cascade="all, delete-orphan"
    )
    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document_version", cascade="all, delete-orphan"
    )


class Chapter(Base):
    __tablename__ = "chapters"
    __table_args__ = (
        UniqueConstraint(
            "document_version_id", "chapter_key", name="uq_chapters_version_chapter_key"
        ),
        CheckConstraint("level >= 0", name="ck_chapters_level"),
        CheckConstraint("sort_order >= 0", name="ck_chapters_sort_order"),
        CheckConstraint("pdf_page_index_start >= 0", name="ck_chapters_pdf_page_start"),
        CheckConstraint(
            "pdf_page_index_end >= pdf_page_index_start", name="ck_chapters_pdf_page_range"
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_chapters_confidence",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_version_id: Mapped[int] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"), nullable=True, index=True
    )
    chapter_key: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    pdf_page_index_start: Mapped[int] = mapped_column(Integer, nullable=False)
    pdf_page_index_end: Mapped[int] = mapped_column(Integer, nullable=False)
    printed_page_start_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    printed_page_end_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    recognition_method: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())

    document_version: Mapped[DocumentVersion] = relationship(back_populates="chapters")
    parent: Mapped[Chapter | None] = relationship(
        back_populates="children", remote_side="Chapter.id"
    )
    children: Mapped[list[Chapter]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )
    chunks: Mapped[list[DocumentChunk]] = relationship(back_populates="chapter")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_version_id", "chunk_key", name="uq_document_chunks_version_chunk_key"
        ),
        CheckConstraint("pdf_page_index_start >= 0", name="ck_document_chunks_pdf_page_start"),
        CheckConstraint(
            "pdf_page_index_end >= pdf_page_index_start",
            name="ck_document_chunks_pdf_page_range",
        ),
        CheckConstraint(
            "quality_status IN ('ready', 'needs_review', 'failed')",
            name="ck_document_chunks_quality_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_version_id: Mapped[int] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chapter_id: Mapped[int | None] = mapped_column(
        ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    chunk_key: Mapped[str] = mapped_column(String(128), nullable=False)
    chapter_path: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON), default=list, server_default=text("'[]'")
    )
    pdf_page_index_start: Mapped[int] = mapped_column(Integer, nullable=False)
    pdf_page_index_end: Mapped[int] = mapped_column(Integer, nullable=False)
    printed_page_labels: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON), default=list, server_default=text("'[]'")
    )
    block_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    cleaned_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    quality_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    quality_flags: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON), default=list, server_default=text("'[]'")
    )
    pipeline_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())

    document_version: Mapped[DocumentVersion] = relationship(back_populates="chunks")
    chapter: Mapped[Chapter | None] = relationship(back_populates="chunks")
    card_sources: Mapped[list[CardSource]] = relationship(back_populates="document_chunk")


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    subject: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    cards: Mapped[list[Card]] = relationship(back_populates="book")


class Card(Base):
    __tablename__ = "cards"
    __table_args__ = (UniqueConstraint("external_id", name="uq_cards_external_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(128), index=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), index=True)
    chapter: Mapped[str | None] = mapped_column(String(128), nullable=True)
    section: Mapped[str | None] = mapped_column(String(128), nullable=True)
    card_type: Mapped[str] = mapped_column(String(64), default="other")
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    answer_points_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_excerpt: Mapped[str] = mapped_column(Text, default="")
    source_pages_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="approved", index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    content_revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    answer_points: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON), default=list, server_default=text("'[]'")
    )
    tags: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON), default=list, server_default=text("'[]'")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    book: Mapped[Book] = relationship(back_populates="cards")
    review_state: Mapped[ReviewState | None] = relationship(
        "ReviewState", back_populates="card", uselist=False
    )
    sources: Mapped[list[CardSource]] = relationship(
        back_populates="card", cascade="all, delete-orphan", order_by="CardSource.citation_order"
    )


class CardSource(Base):
    __tablename__ = "card_sources"
    __table_args__ = (
        UniqueConstraint("card_id", "citation_order", name="uq_card_sources_card_order"),
        UniqueConstraint("card_id", "document_chunk_id", name="uq_card_sources_card_chunk"),
        CheckConstraint("citation_order >= 0", name="ck_card_sources_citation_order"),
        CheckConstraint("pdf_page_index_start >= 0", name="ck_card_sources_pdf_page_start"),
        CheckConstraint(
            "pdf_page_index_end >= pdf_page_index_start", name="ck_card_sources_pdf_page_range"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_chunk_id: Mapped[int] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    citation_order: Mapped[int] = mapped_column(Integer, nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    pdf_page_index_start: Mapped[int] = mapped_column(Integer, nullable=False)
    pdf_page_index_end: Mapped[int] = mapped_column(Integer, nullable=False)
    printed_page_start_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    printed_page_end_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())

    card: Mapped[Card] = relationship(back_populates="sources")
    document_chunk: Mapped[DocumentChunk] = relationship(back_populates="card_sources")
