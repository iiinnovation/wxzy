from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from .models import Book, Card, CardSource, Chapter, Document, DocumentChunk, DocumentVersion
from .schemas import (
    CardSourceOut,
    CatalogCardCreate,
    ChapterCreate,
    DocumentChunkCreate,
    DocumentCreate,
    DocumentVersionCreate,
)


class CatalogConflictError(RuntimeError):
    pass


class CatalogReferenceError(RuntimeError):
    pass


@dataclass(frozen=True)
class DocumentVersionRegistration:
    document: Document
    version: DocumentVersion
    created: bool


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime values must include a timezone")
    return value.astimezone(UTC)


def _document_identity(document: Document) -> tuple[str, str | None, str | None, str, str | None]:
    return (
        document.title,
        document.subject,
        document.edition_note,
        document.copyright_scope,
        document.copyright_notice,
    )


def _document_values_identity(
    values: DocumentCreate,
) -> tuple[str, str | None, str | None, str, str | None]:
    return (
        values.title,
        values.subject,
        values.edition_note,
        values.copyright_scope.value,
        values.copyright_notice,
    )


def register_document_version(
    db: Session,
    *,
    document_values: DocumentCreate,
    version_values: DocumentVersionCreate,
    now: datetime | None = None,
) -> DocumentVersionRegistration:
    timestamp = _require_aware_utc(now or _utc_now())
    document = db.scalar(
        select(Document).where(Document.document_key == document_values.document_key).limit(1)
    )
    if document is not None and _document_identity(document) != _document_values_identity(
        document_values
    ):
        raise CatalogConflictError(
            f"document_key {document_values.document_key!r} already belongs to another title"
        )

    if document is None:
        document = Document(
            document_key=document_values.document_key,
            title=document_values.title,
            subject=document_values.subject,
            edition_note=document_values.edition_note,
            copyright_scope=document_values.copyright_scope.value,
            copyright_notice=document_values.copyright_notice,
            created_at=timestamp,
            updated_at=timestamp,
        )
        db.add(document)

    try:
        db.flush()
        existing = db.scalar(
            select(DocumentVersion)
            .where(
                DocumentVersion.document_id == document.id,
                DocumentVersion.source_sha256 == version_values.source_sha256,
            )
            .limit(1)
        )
        if existing is not None:
            return DocumentVersionRegistration(document=document, version=existing, created=False)

        version = DocumentVersion(
            document_id=document.id,
            source_sha256=version_values.source_sha256,
            source_file_name=version_values.source_file_name,
            page_count=version_values.page_count,
            size_bytes=version_values.size_bytes,
            processing_version=version_values.processing_version,
            status=version_values.status.value,
            registered_at=timestamp,
            updated_at=timestamp,
        )
        db.add(version)
        db.commit()
        db.refresh(document)
        db.refresh(version)
        return DocumentVersionRegistration(document=document, version=version, created=True)
    except IntegrityError as exc:
        db.rollback()
        document = db.scalar(
            select(Document).where(Document.document_key == document_values.document_key).limit(1)
        )
        if document is not None:
            if _document_identity(document) != _document_values_identity(document_values):
                raise CatalogConflictError(
                    "document registration conflicts with existing metadata"
                ) from exc
            existing = db.scalar(
                select(DocumentVersion)
                .where(
                    DocumentVersion.document_id == document.id,
                    DocumentVersion.source_sha256 == version_values.source_sha256,
                )
                .limit(1)
            )
            if existing is not None:
                return DocumentVersionRegistration(
                    document=document, version=existing, created=False
                )
        raise CatalogConflictError(
            "document version registration conflicts with existing data"
        ) from exc


def create_chapter(db: Session, values: ChapterCreate, *, now: datetime | None = None) -> Chapter:
    version = db.get(DocumentVersion, values.document_version_id)
    if version is None:
        raise CatalogReferenceError("document version does not exist")
    if values.pdf_page_index_end >= version.page_count:
        raise CatalogReferenceError("chapter PDF page range exceeds the document version")
    if values.parent_id is not None:
        parent = db.get(Chapter, values.parent_id)
        if parent is None or parent.document_version_id != version.id:
            raise CatalogReferenceError("parent chapter must belong to the same document version")

    chapter = Chapter(
        document_version_id=version.id,
        parent_id=values.parent_id,
        chapter_key=values.chapter_key,
        title=values.title,
        level=values.level,
        sort_order=values.sort_order,
        pdf_page_index_start=values.pdf_page_index_start,
        pdf_page_index_end=values.pdf_page_index_end,
        printed_page_start_label=values.printed_page_start_label,
        printed_page_end_label=values.printed_page_end_label,
        recognition_method=values.recognition_method,
        confidence=values.confidence,
        created_at=_require_aware_utc(now or _utc_now()),
    )
    db.add(chapter)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise CatalogConflictError("chapter conflicts with existing data") from exc
    db.refresh(chapter)
    return chapter


def create_document_chunk(
    db: Session, values: DocumentChunkCreate, *, now: datetime | None = None
) -> DocumentChunk:
    version = db.get(DocumentVersion, values.document_version_id)
    if version is None:
        raise CatalogReferenceError("document version does not exist")
    if values.pdf_page_index_end >= version.page_count:
        raise CatalogReferenceError("chunk PDF page range exceeds the document version")
    if values.chapter_id is not None:
        chapter = db.get(Chapter, values.chapter_id)
        if chapter is None or chapter.document_version_id != version.id:
            raise CatalogReferenceError("chunk chapter must belong to the same document version")
        if (
            values.pdf_page_index_start < chapter.pdf_page_index_start
            or values.pdf_page_index_end > chapter.pdf_page_index_end
        ):
            raise CatalogReferenceError("chunk PDF page range must stay within its chapter")

    chunk = DocumentChunk(
        document_version_id=version.id,
        chapter_id=values.chapter_id,
        chunk_key=values.chunk_key,
        chapter_path=list(values.chapter_path),
        pdf_page_index_start=values.pdf_page_index_start,
        pdf_page_index_end=values.pdf_page_index_end,
        printed_page_labels=list(values.printed_page_labels),
        block_type=values.block_type,
        source_text=values.source_text,
        cleaned_text=values.cleaned_text,
        content_hash=values.content_hash,
        quality_status=values.quality_status.value,
        quality_flags=list(values.quality_flags),
        pipeline_version=values.pipeline_version,
        created_at=_require_aware_utc(now or _utc_now()),
    )
    db.add(chunk)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise CatalogConflictError("document chunk conflicts with existing data") from exc
    db.refresh(chunk)
    return chunk


def create_catalog_card(db: Session, values: CatalogCardCreate) -> Card:
    if db.get(Book, values.book_id) is None:
        raise CatalogReferenceError("catalog book does not exist")

    chunk_ids = [source.document_chunk_id for source in values.sources]
    chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.id.in_(chunk_ids))).all()
    chunks_by_id = {chunk.id: chunk for chunk in chunks}
    if set(chunks_by_id) != set(chunk_ids):
        raise CatalogReferenceError("one or more source chunks do not exist")
    for source in values.sources:
        chunk = chunks_by_id[source.document_chunk_id]
        if chunk.quality_status != "ready":
            raise CatalogReferenceError("only ready chunks can be cited by a published card")
        if (
            source.pdf_page_index_start < chunk.pdf_page_index_start
            or source.pdf_page_index_end > chunk.pdf_page_index_end
        ):
            raise CatalogReferenceError("card source PDF range must stay within its chunk")

    ordered_sources = sorted(values.sources, key=lambda source: source.citation_order)
    card = Card(
        external_id=values.external_id,
        book_id=values.book_id,
        card_type=values.card_type,
        question=values.question,
        answer=values.answer,
        answer_points_json=None,
        source_excerpt=ordered_sources[0].excerpt,
        source_pages_json=None,
        tags_json=None,
        status="published",
        content_revision=values.content_revision,
        content_hash=values.content_hash,
        answer_points=list(values.answer_points),
        tags=list(values.tags),
    )
    db.add(card)
    try:
        db.flush()
        for source in ordered_sources:
            db.add(
                CardSource(
                    card_id=card.id,
                    document_chunk_id=source.document_chunk_id,
                    citation_order=source.citation_order,
                    excerpt=source.excerpt,
                    pdf_page_index_start=source.pdf_page_index_start,
                    pdf_page_index_end=source.pdf_page_index_end,
                    printed_page_start_label=source.printed_page_start_label,
                    printed_page_end_label=source.printed_page_end_label,
                )
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise CatalogConflictError("catalog card conflicts with existing data") from exc
    db.refresh(card)
    return card


def list_card_source_contracts(db: Session, *, card_id: int) -> list[CardSourceOut]:
    sources = db.scalars(
        select(CardSource)
        .options(
            joinedload(CardSource.document_chunk)
            .joinedload(DocumentChunk.document_version)
            .joinedload(DocumentVersion.document)
        )
        .where(CardSource.card_id == card_id)
        .order_by(CardSource.citation_order)
    ).all()
    result: list[CardSourceOut] = []
    for source in sources:
        chunk = source.document_chunk
        version = chunk.document_version
        result.append(
            CardSourceOut(
                id=source.id,
                card_id=source.card_id,
                citation_order=source.citation_order,
                document_key=version.document.document_key,
                document_title=version.document.title,
                document_version_id=version.id,
                chunk_key=chunk.chunk_key,
                chapter_path=list(chunk.chapter_path),
                excerpt=source.excerpt,
                pdf_page_index_start=source.pdf_page_index_start,
                pdf_page_index_end=source.pdf_page_index_end,
                pdf_page_number_start=source.pdf_page_index_start + 1,
                pdf_page_number_end=source.pdf_page_index_end + 1,
                printed_page_start_label=source.printed_page_start_label,
                printed_page_end_label=source.printed_page_end_label,
            )
        )
    return result
