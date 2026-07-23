from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.catalog.models import (
    Book,
    Card,
    CardSource,
    Chapter,
    Document,
    DocumentChunk,
    DocumentVersion,
)
from app.catalog.schemas import (
    CardSourceCreate,
    CatalogCardCreate,
    ChapterCreate,
    ChunkQualityStatus,
    DocumentChunkCreate,
    DocumentCreate,
    DocumentVersionCreate,
)
from app.catalog.services import (
    CatalogConflictError,
    CatalogReferenceError,
    card_to_out,
    create_catalog_card,
    create_chapter,
    create_document_chunk,
    list_card_source_contracts,
    register_document_version,
)
from app.db import engine
from app.models import ReviewState


def _clean_catalog_rows(db: Session) -> None:
    db.execute(delete(CardSource))
    db.execute(delete(Card).where(Card.external_id.like("catalog-test-%")))
    db.execute(delete(DocumentChunk))
    db.execute(delete(Chapter))
    db.execute(delete(DocumentVersion))
    db.execute(delete(Document))
    db.execute(delete(Book).where(Book.name.like("Catalog Test%")))
    db.commit()


@pytest.fixture
def db() -> Iterator[Session]:
    with Session(engine) as session:
        _clean_catalog_rows(session)
        yield session
        session.rollback()
        _clean_catalog_rows(session)


def _register_version(db: Session, *, document_key: str = "catalog-test-fangji") -> DocumentVersion:
    registration = register_document_version(
        db,
        document_values=DocumentCreate(
            document_key=document_key,
            title="学霸笔记-方剂学",
            subject="方剂学",
            copyright_scope="personal_use",
        ),
        version_values=DocumentVersionCreate(
            source_sha256="A" * 64,
            source_file_name="fangji.pdf",
            page_count=140,
            size_bytes=343_816_000,
            processing_version="pipeline-v2",
        ),
        now=datetime(2026, 7, 22, 2, 0, tzinfo=UTC),
    )
    return registration.version


def _create_chapter(db: Session, version: DocumentVersion) -> Chapter:
    return create_chapter(
        db,
        ChapterCreate(
            document_version_id=version.id,
            chapter_key="chapter-09-jiebiao",
            title="第九章 解表剂",
            level=1,
            sort_order=9,
            pdf_page_index_start=19,
            pdf_page_index_end=29,
            printed_page_start_label="294",
            printed_page_end_label="304",
            recognition_method="heading_layout",
            confidence=0.96,
        ),
    )


def _create_chunk(
    db: Session,
    *,
    version: DocumentVersion,
    chapter: Chapter,
    chunk_key: str,
    page_index: int,
    printed_page: str,
    quality_status: ChunkQualityStatus = ChunkQualityStatus.READY,
) -> DocumentChunk:
    return create_document_chunk(
        db,
        DocumentChunkCreate(
            document_version_id=version.id,
            chapter_id=chapter.id,
            chunk_key=chunk_key,
            chapter_path=["方剂学", "第九章 解表剂"],
            pdf_page_index_start=page_index,
            pdf_page_index_end=page_index,
            printed_page_labels=[printed_page],
            block_type="table",
            source_text=f"原始内容 {chunk_key}",
            cleaned_text=f"清洗内容 {chunk_key}",
            content_hash=("b" if page_index == 19 else "c") * 64,
            quality_status=quality_status,
            quality_flags=[],
            pipeline_version="pipeline-v2",
        ),
    )


def test_document_version_registration_is_idempotent_by_document_and_hash(db: Session) -> None:
    now = datetime(2026, 7, 22, 2, 0, tzinfo=UTC)
    document_values = DocumentCreate(
        document_key=" Catalog-Test-Fangji ",
        title=" 学霸笔记-方剂学 ",
        subject="方剂学",
    )
    version_values = DocumentVersionCreate(
        source_sha256="A" * 64,
        source_file_name="fangji.pdf",
        page_count=140,
        size_bytes=343_816_000,
        processing_version="pipeline-v2",
    )

    first = register_document_version(
        db, document_values=document_values, version_values=version_values, now=now
    )
    second = register_document_version(
        db, document_values=document_values, version_values=version_values, now=now
    )

    assert first.created is True
    assert second.created is False
    assert second.document.id == first.document.id
    assert second.version.id == first.version.id
    assert second.version.source_sha256 == "a" * 64
    assert second.version.registered_at == now
    assert second.version.registered_at.tzinfo is UTC
    assert db.scalar(select(func.count()).select_from(Document)) == 1
    assert db.scalar(select(func.count()).select_from(DocumentVersion)) == 1

    with pytest.raises(CatalogConflictError):
        register_document_version(
            db,
            document_values=DocumentCreate(
                document_key="catalog-test-fangji",
                title="另一本书",
            ),
            version_values=version_values,
        )


@pytest.mark.parametrize("source_file_name", ["/tmp/fangji.pdf", "C:\\private\\fangji.pdf"])
def test_document_version_rejects_local_paths(source_file_name: str) -> None:
    with pytest.raises(ValidationError, match="without a path"):
        DocumentVersionCreate(
            source_sha256="a" * 64,
            source_file_name=source_file_name,
            page_count=140,
            size_bytes=100,
            processing_version="pipeline-v2",
        )


def test_card_can_cite_multiple_chunks_with_unambiguous_source_contract(db: Session) -> None:
    version = _register_version(db)
    chapter = _create_chapter(db, version)
    first_chunk = _create_chunk(
        db,
        version=version,
        chapter=chapter,
        chunk_key="chunk-guizhi-compose",
        page_index=19,
        printed_page="294",
    )
    second_chunk = _create_chunk(
        db,
        version=version,
        chapter=chapter,
        chunk_key="chunk-guizhi-function",
        page_index=20,
        printed_page="卷四-295",
    )
    book = Book(name="Catalog Test 方剂学", subject="方剂学")
    db.add(book)
    db.commit()

    card = create_catalog_card(
        db,
        CatalogCardCreate(
            external_id="catalog-test-guizhi",
            book_id=book.id,
            content_revision=1,
            content_hash="d" * 64,
            card_type="formula_summary",
            question="桂枝汤的组成和功用是什么？",
            answer="由桂枝、芍药等组成，功用为解肌发表、调和营卫。",
            answer_points=["组成", "功用"],
            tags=["桂枝汤", "解表剂"],
            sources=[
                CardSourceCreate(
                    document_chunk_id=first_chunk.id,
                    citation_order=0,
                    excerpt="桂枝汤组成：桂枝、芍药、生姜、大枣、炙甘草。",
                    pdf_page_index_start=19,
                    pdf_page_index_end=19,
                    printed_page_start_label="294",
                    printed_page_end_label="294",
                ),
                CardSourceCreate(
                    document_chunk_id=second_chunk.id,
                    citation_order=1,
                    excerpt="功用：解肌发表，调和营卫。",
                    pdf_page_index_start=20,
                    pdf_page_index_end=20,
                    printed_page_start_label="卷四-295",
                    printed_page_end_label="卷四-295",
                ),
            ],
        ),
    )

    assert card.content_revision == 1
    assert card.content_hash == "d" * 64
    assert card.answer_points == ["组成", "功用"]
    assert card.tags == ["桂枝汤", "解表剂"]
    assert card.answer_points_json is None
    assert card.tags_json is None
    assert len(card.sources) == 2
    assert card_to_out(card).source_pages == [20, 21]
    assert db.scalar(select(ReviewState.id).where(ReviewState.card_id == card.id)) is None

    contracts = list_card_source_contracts(db, card_id=card.id)
    assert [source.chunk_key for source in contracts] == [
        "chunk-guizhi-compose",
        "chunk-guizhi-function",
    ]
    first = contracts[0].model_dump()
    assert first == {
        "id": contracts[0].id,
        "card_id": card.id,
        "citation_order": 0,
        "document_key": "catalog-test-fangji",
        "document_title": "学霸笔记-方剂学",
        "document_version_id": version.id,
        "chunk_key": "chunk-guizhi-compose",
        "chapter_path": ["方剂学", "第九章 解表剂"],
        "excerpt": "桂枝汤组成：桂枝、芍药、生姜、大枣、炙甘草。",
        "pdf_page_index_start": 19,
        "pdf_page_index_end": 19,
        "pdf_page_number_start": 20,
        "pdf_page_number_end": 20,
        "printed_page_start_label": "294",
        "printed_page_end_label": "294",
    }
    assert contracts[1].pdf_page_number_start == 21
    assert contracts[1].printed_page_start_label == "卷四-295"
    forbidden = {
        "source_file_name",
        "source_text",
        "cleaned_text",
        "processing_version",
        "local_path",
    }
    assert forbidden.isdisjoint(first)


def test_published_card_rejects_non_ready_source_without_partial_write(db: Session) -> None:
    version = _register_version(db, document_key="catalog-test-needs-review")
    chapter = _create_chapter(db, version)
    chunk = _create_chunk(
        db,
        version=version,
        chapter=chapter,
        chunk_key="chunk-needs-review",
        page_index=19,
        printed_page="294",
        quality_status=ChunkQualityStatus.NEEDS_REVIEW,
    )
    book = Book(name="Catalog Test 待复核", subject="方剂学")
    db.add(book)
    db.commit()

    with pytest.raises(CatalogReferenceError, match="only ready"):
        create_catalog_card(
            db,
            CatalogCardCreate(
                external_id="catalog-test-rejected",
                book_id=book.id,
                content_hash="e" * 64,
                card_type="formula",
                question="问题",
                answer="答案",
                sources=[
                    CardSourceCreate(
                        document_chunk_id=chunk.id,
                        citation_order=0,
                        excerpt="待复核来源",
                        pdf_page_index_start=19,
                        pdf_page_index_end=19,
                    )
                ],
            ),
        )

    assert (
        db.scalar(
            select(func.count())
            .select_from(Card)
            .where(Card.external_id == "catalog-test-rejected")
        )
        == 0
    )


def test_source_schema_rejects_reversed_pages_and_duplicate_chunks() -> None:
    with pytest.raises(ValidationError, match="must not precede"):
        CardSourceCreate(
            document_chunk_id=1,
            citation_order=0,
            excerpt="来源",
            pdf_page_index_start=4,
            pdf_page_index_end=3,
        )

    source = CardSourceCreate(
        document_chunk_id=1,
        citation_order=0,
        excerpt="来源",
        pdf_page_index_start=3,
        pdf_page_index_end=3,
    )
    with pytest.raises(ValidationError, match="same chunk"):
        CatalogCardCreate(
            external_id="catalog-test-duplicate-source",
            book_id=1,
            content_hash="f" * 64,
            card_type="definition",
            question="问题",
            answer="答案",
            sources=[source, source.model_copy(update={"citation_order": 1})],
        )
