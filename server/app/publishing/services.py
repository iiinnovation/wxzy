from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..catalog.models import (
    Book,
    Card,
    CardSource,
    Chapter,
    Document,
    DocumentChunk,
    DocumentVersion,
)
from ..config import get_settings
from ..core.errors import InvalidRequestError, ResourceNotFoundError
from ..learning.fsrs_adapter import utcnow
from ..models import ReviewState
from ..schemas import ImportResult
from .models import PublicationImport
from .schemas import (
    CompatibilityCardImport,
    PublicationConflict,
    PublicationCounts,
    PublicationImportResult,
    PublicationStats,
    PublicationStatusOut,
    PublicationValidateResult,
)

REQUIRED_PACKAGE_FILES = (
    "manifest.json",
    "documents.json",
    "chapters.json",
    "chunks.jsonl",
    "cards.jsonl",
    "card_sources.jsonl",
    "checksums.json",
    "quality-summary.json",
)

HASHED_PACKAGE_FILES = (
    "documents.json",
    "chapters.json",
    "chunks.jsonl",
    "cards.jsonl",
    "card_sources.jsonl",
    "quality-summary.json",
)

ABS_PATH_RE = re.compile(r"(^|[\s\"'])/(Users|home|var|tmp|private|etc)/")
SECRET_KEY_RE = re.compile(r"(api[_-]?key|secret|token|password|openid)", re.I)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stable_external_id(card: CompatibilityCardImport) -> str:
    if card.external_id:
        return card.external_id
    fingerprint = json.dumps(
        {
            "book": card.book_name,
            "chapter": card.chapter,
            "section": card.section,
            "question": card.question,
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return f"gen-{hashlib.sha1(fingerprint).hexdigest()[:16]}"


def import_payload(
    db: Session, payload: dict[str, Any], *, only_approved: bool = True
) -> ImportResult:
    cards_in = payload.get("cards") if isinstance(payload, dict) else None
    if not isinstance(cards_in, list):
        raise InvalidRequestError(
            code="INVALID_IMPORT_PAYLOAD",
            message="卡片导入数据格式无效",
        )

    books_created = 0
    cards_upserted = 0
    review_created = 0
    skipped = 0
    book_cache: dict[str, Book] = {}

    try:
        for index, raw in enumerate(cards_in):
            if not isinstance(raw, dict):
                continue
            status = str(raw.get("status") or "candidate").strip() or "candidate"
            if only_approved and status != "approved":
                skipped += 1
                continue

            question = str(raw.get("question") or "").strip()
            answer = str(raw.get("answer") or "").strip()
            if not question or not answer:
                skipped += 1
                continue

            try:
                values = CompatibilityCardImport.model_validate(raw)
            except ValidationError as exc:
                raise InvalidRequestError(
                    code="INVALID_IMPORT_CARD",
                    message="卡片导入字段无效",
                    details={"card_index": index},
                ) from exc

            book_name = values.book_name
            if book_name not in book_cache:
                book = db.scalar(select(Book).where(Book.name == book_name))
                if book is None:
                    book = Book(name=book_name, subject=None)
                    db.add(book)
                    db.flush()
                    books_created += 1
                book_cache[book_name] = book
            book = book_cache[book_name]

            external_id = _stable_external_id(values)
            card = db.scalar(select(Card).where(Card.external_id == external_id))
            if card is None:
                card = Card(external_id=external_id, book_id=book.id)
                db.add(card)

            card.book_id = book.id
            card.chapter = values.chapter
            card.section = values.section
            card.card_type = values.card_type
            card.question = values.question
            card.answer = values.answer
            card.answer_points = list(values.answer_points)
            card.answer_points_json = None
            card.source_excerpt = values.source_excerpt
            # Candidate v1 has no chunk identity. Keep source pages in the read-only
            # compatibility column until P5 publishes them as CardSource rows.
            card.source_pages_json = json.dumps(values.source_pages, ensure_ascii=False)
            card.tags = list(values.tags)
            card.tags_json = None
            card.status = "approved" if only_approved else values.status
            card.confidence = values.confidence
            db.flush()

            # This is deliberately the legacy state used by the compatibility API. It
            # never creates the user-scoped CardReviewState used by the target domain.
            # Keep the old adapter's behavior for ``only_approved=False`` as well; the
            # legacy due query still excludes non-approved cards.
            legacy_state = db.scalar(
                select(ReviewState).where(ReviewState.card_id == card.id).limit(1)
            )
            if legacy_state is None:
                db.add(
                    ReviewState(
                        card_id=card.id,
                        due_at=utcnow(),
                        algorithm_version=get_settings().algorithm_version,
                    )
                )
                review_created += 1
            cards_upserted += 1
        db.commit()
    except Exception:
        db.rollback()
        raise

    return ImportResult(
        books_created=books_created,
        cards_upserted=cards_upserted,
        review_states_created=review_created,
        skipped_non_approved=skipped,
    )


def _contains_abs_path(value: Any) -> bool:
    if isinstance(value, str):
        return bool(ABS_PATH_RE.search(value)) or value.startswith(
            ("/Users/", "/home/", "/var/", "/tmp/", "/private/")
        )
    if isinstance(value, dict):
        return any(_contains_abs_path(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_abs_path(v) for v in value)
    return False


def _contains_secret_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            if SECRET_KEY_RE.search(str(key)):
                return True
            if _contains_secret_key(nested):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_secret_key(v) for v in value)
    return False


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name}: invalid JSONL at line {line_no}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{path.name}: JSONL row {line_no} must be an object")
        rows.append(payload)
    return rows


def _recompute_file_checksums(package_dir: Path) -> dict[str, str]:
    return {
        name: _sha256_bytes((package_dir / name).read_bytes()) for name in HASHED_PACKAGE_FILES
    }


def _as_counts(raw: dict[str, Any] | None) -> PublicationCounts:
    raw = raw or {}
    return PublicationCounts(
        documents=int(raw.get("documents") or 0),
        chapters=int(raw.get("chapters") or 0),
        chunks=int(raw.get("chunks") or 0),
        cards=int(raw.get("cards") or 0),
        card_sources=int(raw.get("card_sources") or 0),
    )


def _as_stats(raw: dict[str, Any] | None) -> PublicationStats:
    raw = raw or {}
    return PublicationStats(**{k: int(raw.get(k) or 0) for k in PublicationStats.model_fields})


def _as_conflicts(raw: list[Any] | None) -> list[PublicationConflict]:
    conflicts: list[PublicationConflict] = []
    for item in raw or []:
        if isinstance(item, PublicationConflict):
            conflicts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        conflicts.append(
            PublicationConflict(
                entity=str(item.get("entity") or "unknown"),
                identity=str(item.get("identity") or ""),
                reason=str(item.get("reason") or ""),
                details=dict(item.get("details") or {}),
            )
        )
    return conflicts


def _record_to_status(row: PublicationImport) -> PublicationStatusOut:
    return PublicationStatusOut(
        publication_id=row.publication_id,
        manifest_hash=row.manifest_hash,
        package_hash=row.package_hash,
        schema_version=row.schema_version,
        status=row.status,  # type: ignore[arg-type]
        pipeline_version=row.pipeline_version,
        generation_version=row.generation_version,
        review_version=row.review_version,
        counts=_as_counts(row.counts if isinstance(row.counts, dict) else {}),
        stats=_as_stats(row.stats if isinstance(row.stats, dict) else {}),
        conflicts=_as_conflicts(row.conflicts if isinstance(row.conflicts, list) else []),
        error_message=row.error_message,
        imported_at=row.imported_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _record_to_import_result(
    row: PublicationImport, *, idempotent_replay: bool = False
) -> PublicationImportResult:
    status = _record_to_status(row)
    return PublicationImportResult(
        publication_id=status.publication_id,
        manifest_hash=status.manifest_hash,
        package_hash=status.package_hash,
        schema_version=status.schema_version,
        status=status.status,
        idempotent_replay=idempotent_replay,
        counts=status.counts,
        stats=status.stats,
        conflicts=status.conflicts,
        error_message=status.error_message,
        imported_at=status.imported_at,
        created_at=status.created_at,
        updated_at=status.updated_at,
    )


@dataclass
class LoadedPublicationPackage:
    package_dir: Path
    manifest: dict[str, Any]
    documents: list[dict[str, Any]]
    chapters: list[dict[str, Any]]
    chunks: list[dict[str, Any]]
    cards: list[dict[str, Any]]
    card_sources: list[dict[str, Any]]
    checksums: dict[str, Any]
    quality_summary: dict[str, Any]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def publication_id(self) -> str:
        return str(self.manifest.get("publication_id") or "")

    @property
    def manifest_hash(self) -> str:
        return str(self.manifest.get("manifest_hash") or "")

    @property
    def package_hash(self) -> str:
        return str(self.manifest.get("package_hash") or self.checksums.get("package_hash") or "")


def load_publication_package(package_dir: Path | str) -> LoadedPublicationPackage:
    root = Path(package_dir).expanduser().resolve()
    errors: list[str] = []
    warnings: list[str] = []
    if not root.is_dir():
        raise InvalidRequestError(
            code="PUBLICATION_PACKAGE_NOT_FOUND",
            message="发布包目录不存在",
            details={"package_dir": str(root)},
        )

    missing = [name for name in REQUIRED_PACKAGE_FILES if not (root / name).is_file()]
    if missing:
        raise InvalidRequestError(
            code="PUBLICATION_PACKAGE_INCOMPLETE",
            message="发布包缺少必需文件",
            details={"missing": missing, "package_dir": str(root)},
        )

    try:
        manifest = _read_json(root / "manifest.json")
        documents = _read_json(root / "documents.json")
        chapters = _read_json(root / "chapters.json")
        quality_summary = _read_json(root / "quality-summary.json")
        checksums = _read_json(root / "checksums.json")
        chunks = _read_jsonl(root / "chunks.jsonl")
        cards = _read_jsonl(root / "cards.jsonl")
        card_sources = _read_jsonl(root / "card_sources.jsonl")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise InvalidRequestError(
            code="PUBLICATION_PACKAGE_UNREADABLE",
            message="发布包无法读取或解析",
            details={"error": str(exc)},
        ) from exc

    if not isinstance(manifest, dict):
        errors.append("manifest.json must be an object")
        manifest = {}
    if not isinstance(documents, list):
        errors.append("documents.json must be a list")
        documents = []
    if not isinstance(chapters, list):
        errors.append("chapters.json must be a list")
        chapters = []
    if not isinstance(quality_summary, dict):
        errors.append("quality-summary.json must be an object")
        quality_summary = {}
    if not isinstance(checksums, dict):
        errors.append("checksums.json must be an object")
        checksums = {}

    package = LoadedPublicationPackage(
        package_dir=root,
        manifest=manifest,
        documents=[row for row in documents if isinstance(row, dict)],
        chapters=[row for row in chapters if isinstance(row, dict)],
        chunks=chunks,
        cards=cards,
        card_sources=card_sources,
        checksums=checksums,
        quality_summary=quality_summary,
        errors=errors,
        warnings=warnings,
    )
    return package


def _validate_loaded_package(package: LoadedPublicationPackage) -> PublicationValidateResult:
    errors = list(package.errors)
    warnings = list(package.warnings)
    manifest = package.manifest

    publication_id = str(manifest.get("publication_id") or "").strip()
    if not publication_id:
        errors.append("manifest.publication_id is required")

    schema_version = manifest.get("schema_version")
    if not isinstance(schema_version, int) or schema_version < 1:
        errors.append("manifest.schema_version must be a positive integer")

    recorded_files = (
        manifest.get("checksums")
        if isinstance(manifest.get("checksums"), dict)
        else package.checksums.get("files")
    )
    if not isinstance(recorded_files, dict):
        errors.append("checksum file map missing")
        recorded_files = {}

    actual = _recompute_file_checksums(package.package_dir)
    mismatches = {
        name: {"recorded": recorded_files.get(name), "actual": digest}
        for name, digest in actual.items()
        if recorded_files.get(name) != digest
    }
    if mismatches:
        errors.append(f"checksum mismatches: {sorted(mismatches)}")

    package_hash_actual = _sha256_text(_canonical_json(actual))
    package_hash_recorded = str(
        manifest.get("package_hash") or package.checksums.get("package_hash") or ""
    )
    if package_hash_recorded and package_hash_recorded != package_hash_actual:
        errors.append("package_hash mismatch")

    manifest_for_hash = {
        key: value for key, value in manifest.items() if key != "manifest_hash"
    }
    manifest_hash_actual = _sha256_text(_canonical_json(manifest_for_hash))
    manifest_hash_recorded = str(manifest.get("manifest_hash") or "")
    if manifest_hash_recorded and manifest_hash_recorded != manifest_hash_actual:
        errors.append("manifest_hash mismatch")

    counts = _as_counts(manifest.get("counts") if isinstance(manifest.get("counts"), dict) else None)
    observed = PublicationCounts(
        documents=len(package.documents),
        chapters=len(package.chapters),
        chunks=len(package.chunks),
        cards=len(package.cards),
        card_sources=len(package.card_sources),
    )
    for field_name in PublicationCounts.model_fields:
        if getattr(counts, field_name) and getattr(counts, field_name) != getattr(observed, field_name):
            errors.append(
                f"manifest.counts.{field_name}={getattr(counts, field_name)} "
                f"does not match package rows={getattr(observed, field_name)}"
            )
    counts = observed

    if counts.cards == 0:
        errors.append("publication package contains no cards")

    chunk_ids = {
        str(row.get("id") or row.get("chunk_id") or row.get("chunk_key") or "").strip()
        for row in package.chunks
    }
    chunk_ids.discard("")
    card_ids = {str(row.get("id") or "").strip() for row in package.cards}
    card_ids.discard("")

    for index, card in enumerate(package.cards):
        cid = str(card.get("id") or f"card[{index}]")
        status = str(card.get("status") or "").strip()
        if status != "approved":
            errors.append(f"{cid}: only approved cards may be imported (status={status!r})")
        content_hash = str(card.get("content_hash") or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", content_hash):
            errors.append(f"{cid}: content_hash must be sha256 hex")
        question = str(card.get("question") or "").strip()
        answer = str(card.get("answer") or "").strip()
        if not question or not answer:
            errors.append(f"{cid}: question/answer required")
        book = str(card.get("book") or "").strip()
        if not book:
            errors.append(f"{cid}: book required")
        document_key = str(card.get("document_key") or "").strip()
        if not document_key:
            errors.append(f"{cid}: document_key required")
        if _contains_abs_path(card) or _contains_secret_key(card):
            errors.append(f"{cid}: forbidden absolute path or secret-like field")
        cited = [str(x) for x in (card.get("chunk_ids") or []) if str(x).strip()]
        if not cited:
            # fall back to sources later; keep warning for now
            pass
        for chunk_id in cited:
            if chunk_id not in chunk_ids:
                # chunks may be synthesized from sources only; warn not hard fail until sources checked
                warnings.append(f"{cid}: chunk_id {chunk_id!r} not listed in chunks.jsonl")

    sources_by_card: dict[str, list[dict[str, Any]]] = {}
    for index, source in enumerate(package.card_sources):
        card_id = str(source.get("card_id") or "").strip()
        if not card_id:
            errors.append(f"card_sources[{index}]: missing card_id")
            continue
        if card_id not in card_ids:
            errors.append(f"card_sources[{index}]: unknown card_id {card_id!r}")
        chunk_id = str(source.get("chunk_id") or "").strip()
        if not chunk_id:
            errors.append(f"card_sources[{index}]: missing chunk_id")
        excerpt = str(source.get("excerpt") or "").strip()
        if not excerpt:
            errors.append(f"card_sources[{index}]: empty excerpt")
        sources_by_card.setdefault(card_id, []).append(source)
        if chunk_id and chunk_id not in chunk_ids:
            # allow package to omit full chunk bodies if sources carry identity
            warnings.append(f"card_sources[{index}]: chunk_id {chunk_id!r} not in chunks.jsonl")

    for card in package.cards:
        cid = str(card.get("id") or "").strip()
        if not cid:
            continue
        if not sources_by_card.get(cid) and not (card.get("chunk_ids") or []):
            errors.append(f"{cid}: missing source citations")

    for collection_name, rows in (
        ("documents", package.documents),
        ("chapters", package.chapters),
        ("chunks", package.chunks),
    ):
        if _contains_abs_path(rows) or _contains_secret_key(rows):
            errors.append(f"{collection_name}: forbidden absolute path or secret-like field")

    return PublicationValidateResult(
        ok=not errors,
        publication_id=publication_id or None,
        manifest_hash=manifest_hash_recorded or manifest_hash_actual or None,
        package_hash=package_hash_recorded or package_hash_actual or None,
        schema_version=schema_version if isinstance(schema_version, int) else None,
        counts=counts,
        errors=errors,
        warnings=warnings,
    )


def validate_publication_package(package_dir: Path | str) -> PublicationValidateResult:
    package = load_publication_package(package_dir)
    return _validate_loaded_package(package)


def _deterministic_sha256(*parts: str) -> str:
    return _sha256_text("\0".join(parts))


def _source_file_name(document_key: str, document_version: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9._-]+", "-", document_key).strip("-") or "document"
    return f"{base}.pdf"


def _document_version_label(raw: dict[str, Any], fallback_key: str) -> str:
    return str(
        raw.get("document_version")
        or raw.get("version")
        or raw.get("processing_version")
        or fallback_key
        or "v1"
    ).strip()


def _chunk_identity(raw: dict[str, Any]) -> str:
    return str(raw.get("id") or raw.get("chunk_id") or raw.get("chunk_key") or "").strip()


def _chapter_identity(raw: dict[str, Any]) -> str:
    key = str(raw.get("chapter_key") or raw.get("chapter") or raw.get("title") or "").strip()
    return key or "未分章"


def _ensure_book(db: Session, *, name: str, subject: str | None, stats: PublicationStats) -> Book:
    book = db.scalar(select(Book).where(Book.name == name).limit(1))
    if book is not None:
        stats.books_reused += 1
        return book
    book = Book(name=name, subject=subject)
    db.add(book)
    db.flush()
    stats.books_created += 1
    return book


def _ensure_document_version(
    db: Session,
    *,
    document_key: str,
    title: str,
    subject: str | None,
    document_version_label: str,
    source_sha256: str | None,
    page_count: int,
    size_bytes: int,
    processing_version: str,
    stats: PublicationStats,
    now: datetime,
) -> tuple[Document, DocumentVersion]:
    document = db.scalar(select(Document).where(Document.document_key == document_key).limit(1))
    if document is None:
        document = Document(
            document_key=document_key,
            title=title,
            subject=subject,
            edition_note=document_version_label,
            copyright_scope="personal_use",
            copyright_notice=None,
            created_at=now,
            updated_at=now,
        )
        db.add(document)
        db.flush()
        stats.documents_created += 1
    else:
        # keep existing identity; do not rewrite title conflicts here
        document.updated_at = now

    sha = (source_sha256 or _deterministic_sha256(document_key, document_version_label)).lower()
    version = db.scalar(
        select(DocumentVersion)
        .where(
            DocumentVersion.document_id == document.id,
            DocumentVersion.source_sha256 == sha,
        )
        .limit(1)
    )
    if version is not None:
        stats.document_versions_reused += 1
        if version.status != "published":
            version.status = "published"
            version.updated_at = now
        return document, version

    version = DocumentVersion(
        document_id=document.id,
        source_sha256=sha,
        source_file_name=_source_file_name(document_key, document_version_label),
        page_count=max(page_count, 1),
        size_bytes=max(size_bytes, 1),
        processing_version=processing_version[:64],
        status="published",
        registered_at=now,
        updated_at=now,
    )
    db.add(version)
    db.flush()
    stats.document_versions_created += 1
    return document, version


def _ensure_chapter(
    db: Session,
    *,
    version: DocumentVersion,
    chapter_key: str,
    title: str,
    sort_order: int,
    pdf_page_index_start: int,
    pdf_page_index_end: int,
    printed_page_start_label: str | None,
    printed_page_end_label: str | None,
    stats: PublicationStats,
    now: datetime,
) -> Chapter:
    existing = db.scalar(
        select(Chapter)
        .where(
            Chapter.document_version_id == version.id,
            Chapter.chapter_key == chapter_key,
        )
        .limit(1)
    )
    if existing is not None:
        stats.chapters_reused += 1
        return existing
    chapter = Chapter(
        document_version_id=version.id,
        parent_id=None,
        chapter_key=chapter_key[:128],
        title=title[:256],
        level=1,
        sort_order=max(sort_order, 0),
        pdf_page_index_start=max(pdf_page_index_start, 0),
        pdf_page_index_end=max(pdf_page_index_end, pdf_page_index_start, 0),
        printed_page_start_label=printed_page_start_label,
        printed_page_end_label=printed_page_end_label,
        recognition_method="publication_import",
        confidence=1.0,
        created_at=now,
    )
    db.add(chapter)
    db.flush()
    stats.chapters_created += 1
    return chapter


def _ensure_chunk(
    db: Session,
    *,
    version: DocumentVersion,
    chapter: Chapter | None,
    chunk_key: str,
    chapter_path: list[str],
    pdf_page_index_start: int,
    pdf_page_index_end: int,
    printed_page_labels: list[str],
    block_type: str,
    text: str,
    content_hash: str | None,
    pipeline_version: str,
    stats: PublicationStats,
    now: datetime,
) -> DocumentChunk:
    existing = db.scalar(
        select(DocumentChunk)
        .where(
            DocumentChunk.document_version_id == version.id,
            DocumentChunk.chunk_key == chunk_key,
        )
        .limit(1)
    )
    if existing is not None:
        stats.chunks_reused += 1
        return existing

    body = text.strip() or chunk_key
    digest = (content_hash or _sha256_text(body)).lower()
    chunk = DocumentChunk(
        document_version_id=version.id,
        chapter_id=chapter.id if chapter is not None else None,
        chunk_key=chunk_key[:128],
        chapter_path=list(chapter_path),
        pdf_page_index_start=max(pdf_page_index_start, 0),
        pdf_page_index_end=max(pdf_page_index_end, pdf_page_index_start, 0),
        printed_page_labels=list(printed_page_labels),
        block_type=(block_type or "paragraph")[:64],
        source_text=body,
        cleaned_text=body,
        content_hash=digest,
        quality_status="ready",
        quality_flags=[],
        pipeline_version=pipeline_version[:64],
        created_at=now,
    )
    db.add(chunk)
    db.flush()
    stats.chunks_created += 1
    return chunk


def import_publication_package(
    db: Session, package_dir: Path | str, *, now: datetime | None = None
) -> PublicationImportResult:
    """Validate and import a versioned publication package in one transaction.

    Rules:
    - same publication_id + matching hashes => idempotent replay of stored result
    - same publication_id with different hashes => conflict, no partial write
    - same card external_id with different content_hash => conflict
    - same card external_id with same content_hash => skip
    - never creates ReviewState or CardReviewState
    """
    timestamp = now or _utc_now()
    package = load_publication_package(package_dir)
    validation = _validate_loaded_package(package)
    if not validation.ok:
        raise InvalidRequestError(
            code="PUBLICATION_VALIDATION_FAILED",
            message="发布包校验失败",
            details={"errors": validation.errors, "warnings": validation.warnings},
        )

    publication_id = validation.publication_id or ""
    manifest_hash = validation.manifest_hash or ""
    package_hash = validation.package_hash or ""
    schema_version = int(validation.schema_version or 1)

    existing = db.scalar(
        select(PublicationImport).where(PublicationImport.publication_id == publication_id).limit(1)
    )
    if existing is not None:
        if existing.manifest_hash == manifest_hash and existing.package_hash == package_hash:
            return _record_to_import_result(existing, idempotent_replay=True)
        conflict = PublicationConflict(
            entity="publication",
            identity=publication_id,
            reason="publication_id already imported with different package hash",
            details={
                "existing_manifest_hash": existing.manifest_hash,
                "existing_package_hash": existing.package_hash,
                "incoming_manifest_hash": manifest_hash,
                "incoming_package_hash": package_hash,
            },
        )
        # Do not overwrite the successful import record; report conflict only.
        return PublicationImportResult(
            publication_id=publication_id,
            manifest_hash=manifest_hash,
            package_hash=package_hash,
            schema_version=schema_version,
            status="conflict",
            idempotent_replay=False,
            counts=validation.counts,
            stats=PublicationStats(),
            conflicts=[conflict],
            error_message=conflict.reason,
            imported_at=None,
            created_at=existing.created_at,
            updated_at=existing.updated_at,
        )

    stats = PublicationStats()
    conflicts: list[PublicationConflict] = []
    created_card_ids: list[int] = []
    pipeline_version = str(package.manifest.get("pipeline_version") or "p5")
    generation_version = str(package.manifest.get("generation_version") or "")
    review_version = str(package.manifest.get("review_version") or "")

    # Index package rows.
    docs_by_key: dict[str, dict[str, Any]] = {}
    for row in package.documents:
        key = str(row.get("document_key") or "").strip()
        if key:
            docs_by_key[key] = row

    chapters_by_doc: dict[str, list[dict[str, Any]]] = {}
    for row in package.chapters:
        key = str(row.get("document_key") or "").strip()
        if key:
            chapters_by_doc.setdefault(key, []).append(row)

    chunks_by_id: dict[str, dict[str, Any]] = {}
    for row in package.chunks:
        cid = _chunk_identity(row)
        if cid:
            chunks_by_id[cid] = row

    sources_by_card: dict[str, list[dict[str, Any]]] = {}
    for row in package.card_sources:
        card_id = str(row.get("card_id") or "").strip()
        if card_id:
            sources_by_card.setdefault(card_id, []).append(row)

    version_by_doc_key: dict[str, DocumentVersion] = {}
    chapter_by_pair: dict[tuple[str, str], Chapter] = {}
    chunk_by_key: dict[str, DocumentChunk] = {}

    try:
        # Pre-create documents/versions/chapters/chunks referenced by cards.
        for card in package.cards:
            document_key = str(card.get("document_key") or "").strip()
            document_version_label = str(card.get("document_version") or "v1").strip() or "v1"
            book_name = str(card.get("book") or document_key).strip()
            doc_row = docs_by_key.get(document_key, {})
            title = str(doc_row.get("title") or book_name).strip() or book_name
            subject = doc_row.get("subject")
            subject_text = str(subject).strip() if isinstance(subject, str) and subject.strip() else None

            if document_key not in version_by_doc_key:
                page_count = int(doc_row.get("page_count") or 0)
                size_bytes = int(doc_row.get("size_bytes") or 0)
                # derive page_count from cards/chunks if absent
                if page_count <= 0:
                    pages = [int(p) for p in (card.get("pdf_page_indexes") or []) if isinstance(p, int)]
                    page_count = (max(pages) + 1) if pages else 1
                if size_bytes <= 0:
                    size_bytes = 1
                source_sha = doc_row.get("source_sha256")
                source_sha_text = (
                    str(source_sha).lower()
                    if isinstance(source_sha, str) and re.fullmatch(r"[0-9a-fA-F]{64}", str(source_sha))
                    else None
                )
                _document, version = _ensure_document_version(
                    db,
                    document_key=document_key,
                    title=title,
                    subject=subject_text,
                    document_version_label=_document_version_label(doc_row, document_version_label),
                    source_sha256=source_sha_text,
                    page_count=page_count,
                    size_bytes=size_bytes,
                    processing_version=str(
                        doc_row.get("processing_version") or pipeline_version or "publication"
                    ),
                    stats=stats,
                    now=timestamp,
                )
                # ensure version page_count can cover later page indexes
                version_by_doc_key[document_key] = version

                for chapter_row in chapters_by_doc.get(document_key, []):
                    chapter_key = _chapter_identity(chapter_row)
                    start = int(chapter_row.get("pdf_page_index_start") or 0)
                    end = int(chapter_row.get("pdf_page_index_end") or start)
                    if end >= version.page_count:
                        version.page_count = end + 1
                    chapter = _ensure_chapter(
                        db,
                        version=version,
                        chapter_key=chapter_key,
                        title=str(chapter_row.get("title") or chapter_row.get("chapter") or chapter_key),
                        sort_order=int(chapter_row.get("sort_order") or 0),
                        pdf_page_index_start=start,
                        pdf_page_index_end=end,
                        printed_page_start_label=(
                            str(chapter_row["printed_page_start_label"])
                            if chapter_row.get("printed_page_start_label") is not None
                            else None
                        ),
                        printed_page_end_label=(
                            str(chapter_row["printed_page_end_label"])
                            if chapter_row.get("printed_page_end_label") is not None
                            else None
                        ),
                        stats=stats,
                        now=timestamp,
                    )
                    chapter_by_pair[(document_key, chapter_key)] = chapter

            version = version_by_doc_key[document_key]
            chapter_title = str(card.get("chapter") or "未分章").strip() or "未分章"
            if (document_key, chapter_title) not in chapter_by_pair:
                pages = [int(p) for p in (card.get("pdf_page_indexes") or []) if isinstance(p, int)]
                start = min(pages) if pages else 0
                end = max(pages) if pages else start
                if end >= version.page_count:
                    version.page_count = end + 1
                chapter_by_pair[(document_key, chapter_title)] = _ensure_chapter(
                    db,
                    version=version,
                    chapter_key=chapter_title,
                    title=chapter_title,
                    sort_order=len(chapter_by_pair),
                    pdf_page_index_start=start,
                    pdf_page_index_end=end,
                    printed_page_start_label=(
                        str(card["printed_page_labels"][0])
                        if card.get("printed_page_labels")
                        else None
                    ),
                    printed_page_end_label=(
                        str(card["printed_page_labels"][-1])
                        if card.get("printed_page_labels")
                        else None
                    ),
                    stats=stats,
                    now=timestamp,
                )

            # Ensure chunks for this card's sources / chunk_ids.
            source_rows = list(sources_by_card.get(str(card.get("id") or ""), []))
            if not source_rows:
                for idx, chunk_id in enumerate(card.get("chunk_ids") or []):
                    page = int(card["pdf_page_indexes"][0]) if card.get("pdf_page_indexes") else 0
                    label = (
                        str(card["printed_page_labels"][0])
                        if card.get("printed_page_labels")
                        else None
                    )
                    source_rows.append(
                        {
                            "card_id": card.get("id"),
                            "citation_order": idx,
                            "chunk_id": chunk_id,
                            "excerpt": card.get("source_excerpt") or "",
                            "pdf_page_index_start": page,
                            "pdf_page_index_end": page,
                            "printed_page_start_label": label,
                            "printed_page_end_label": label,
                        }
                    )
            sources_by_card[str(card.get("id") or "")] = source_rows

            for source in source_rows:
                chunk_id = str(source.get("chunk_id") or "").strip()
                if not chunk_id or chunk_id in chunk_by_key:
                    continue
                chunk_row = chunks_by_id.get(chunk_id, {})
                start = int(
                    source.get("pdf_page_index_start")
                    if source.get("pdf_page_index_start") is not None
                    else chunk_row.get("pdf_page_index_start") or 0
                )
                end = int(
                    source.get("pdf_page_index_end")
                    if source.get("pdf_page_index_end") is not None
                    else chunk_row.get("pdf_page_index_end") or start
                )
                if end >= version.page_count:
                    version.page_count = end + 1
                labels: list[str] = []
                if source.get("printed_page_start_label"):
                    labels.append(str(source["printed_page_start_label"]))
                if (
                    source.get("printed_page_end_label")
                    and str(source.get("printed_page_end_label")) not in labels
                ):
                    labels.append(str(source["printed_page_end_label"]))
                if not labels and isinstance(chunk_row.get("printed_page_labels"), list):
                    labels = [str(x) for x in chunk_row["printed_page_labels"]]
                text = str(
                    chunk_row.get("cleaned_text")
                    or chunk_row.get("source_text")
                    or chunk_row.get("text")
                    or chunk_row.get("excerpt")
                    or source.get("excerpt")
                    or chunk_id
                )
                content_hash = chunk_row.get("content_hash")
                content_hash_text = (
                    str(content_hash).lower()
                    if isinstance(content_hash, str)
                    and re.fullmatch(r"[0-9a-fA-F]{64}", str(content_hash))
                    else None
                )
                chapter = chapter_by_pair.get((document_key, chapter_title))
                chunk_by_key[chunk_id] = _ensure_chunk(
                    db,
                    version=version,
                    chapter=chapter,
                    chunk_key=chunk_id,
                    chapter_path=list(chunk_row.get("chapter_path") or [chapter_title]),
                    pdf_page_index_start=start,
                    pdf_page_index_end=end,
                    printed_page_labels=labels,
                    block_type=str(chunk_row.get("block_type") or "paragraph"),
                    text=text,
                    content_hash=content_hash_text,
                    pipeline_version=str(
                        chunk_row.get("pipeline_version") or pipeline_version or "publication"
                    ),
                    stats=stats,
                    now=timestamp,
                )

        # Import cards.
        for card in package.cards:
            external_id = str(card.get("id") or "").strip()
            content_hash = str(card.get("content_hash") or "").strip().lower()
            book_name = str(card.get("book") or "").strip()
            document_key = str(card.get("document_key") or "").strip()
            chapter_title = str(card.get("chapter") or "未分章").strip() or "未分章"
            section = card.get("section")
            section_text = str(section).strip() if isinstance(section, str) and section.strip() else None
            card_type = str(card.get("card_type") or "other").strip() or "other"
            question = str(card.get("question") or "").strip()
            answer = str(card.get("answer") or "").strip()
            answer_points = [
                str(x).strip() for x in (card.get("answer_points") or []) if str(x).strip()
            ]
            tags = [str(x).strip() for x in (card.get("tags") or []) if str(x).strip()]
            source_excerpt = str(card.get("source_excerpt") or "").strip()
            confidence = card.get("confidence")
            confidence_value = float(confidence) if isinstance(confidence, (int, float)) else None

            book = _ensure_book(
                db,
                name=book_name,
                subject=str(docs_by_key.get(document_key, {}).get("subject") or "") or None,
                stats=stats,
            )

            existing_card = db.scalar(select(Card).where(Card.external_id == external_id).limit(1))
            if existing_card is not None:
                existing_hash = (existing_card.content_hash or "").lower()
                if existing_hash and existing_hash == content_hash:
                    stats.cards_skipped += 1
                    continue
                if existing_hash and existing_hash != content_hash:
                    conflicts.append(
                        PublicationConflict(
                            entity="card",
                            identity=external_id,
                            reason="content_hash conflict for stable card id",
                            details={
                                "existing_content_hash": existing_hash,
                                "incoming_content_hash": content_hash,
                                "existing_content_revision": existing_card.content_revision,
                            },
                        )
                    )
                    continue
                # Existing card without content_hash: treat as update to publication metadata.
                existing_card.book_id = book.id
                existing_card.chapter = chapter_title
                existing_card.section = section_text
                existing_card.card_type = card_type
                existing_card.question = question
                existing_card.answer = answer
                existing_card.answer_points = answer_points
                existing_card.answer_points_json = None
                existing_card.source_excerpt = source_excerpt
                existing_card.source_pages_json = None
                existing_card.tags = tags
                existing_card.tags_json = None
                existing_card.status = "published"
                existing_card.confidence = confidence_value
                existing_card.content_hash = content_hash
                existing_card.content_revision = max(int(existing_card.content_revision or 1), 1)
                db.flush()
                # replace sources
                for old in list(existing_card.sources):
                    db.delete(old)
                db.flush()
                target_card = existing_card
                stats.cards_updated += 1
            else:
                target_card = Card(
                    external_id=external_id,
                    book_id=book.id,
                    chapter=chapter_title,
                    section=section_text,
                    card_type=card_type,
                    question=question,
                    answer=answer,
                    answer_points_json=None,
                    source_excerpt=source_excerpt,
                    source_pages_json=None,
                    tags_json=None,
                    status="published",
                    confidence=confidence_value,
                    content_revision=1,
                    content_hash=content_hash,
                    answer_points=answer_points,
                    tags=tags,
                )
                db.add(target_card)
                db.flush()
                stats.cards_created += 1
                created_card_ids.append(target_card.id)

            source_rows = sources_by_card.get(external_id, [])
            ordered = sorted(
                source_rows,
                key=lambda row: int(row.get("citation_order") or 0),
            )
            seen_chunks: set[int] = set()
            citation_order = 0
            for source in ordered:
                chunk_id = str(source.get("chunk_id") or "").strip()
                chunk = chunk_by_key.get(chunk_id)
                if chunk is None:
                    conflicts.append(
                        PublicationConflict(
                            entity="card_source",
                            identity=f"{external_id}:{chunk_id}",
                            reason="source chunk missing after package load",
                            details={"card_id": external_id, "chunk_id": chunk_id},
                        )
                    )
                    continue
                if chunk.id in seen_chunks:
                    continue
                seen_chunks.add(chunk.id)
                start = int(source.get("pdf_page_index_start") or chunk.pdf_page_index_start)
                end = int(source.get("pdf_page_index_end") or chunk.pdf_page_index_end)
                # clamp into chunk range
                start = max(start, chunk.pdf_page_index_start)
                end = min(max(end, start), chunk.pdf_page_index_end)
                excerpt = str(source.get("excerpt") or source_excerpt or chunk.cleaned_text)[:4000]
                db.add(
                    CardSource(
                        card_id=target_card.id,
                        document_chunk_id=chunk.id,
                        citation_order=citation_order,
                        excerpt=excerpt,
                        pdf_page_index_start=start,
                        pdf_page_index_end=end,
                        printed_page_start_label=(
                            str(source["printed_page_start_label"])
                            if source.get("printed_page_start_label") is not None
                            else None
                        ),
                        printed_page_end_label=(
                            str(source["printed_page_end_label"])
                            if source.get("printed_page_end_label") is not None
                            else None
                        ),
                    )
                )
                citation_order += 1
                stats.card_sources_created += 1

            if citation_order == 0:
                conflicts.append(
                    PublicationConflict(
                        entity="card",
                        identity=external_id,
                        reason="card has no resolvable source citations",
                        details={},
                    )
                )

        if conflicts:
            db.rollback()
            return PublicationImportResult(
                publication_id=publication_id,
                manifest_hash=manifest_hash,
                package_hash=package_hash,
                schema_version=schema_version,
                status="conflict",
                counts=validation.counts,
                stats=PublicationStats(),
                conflicts=conflicts,
                error_message="publication import conflicts",
            )

        # Safety: newly created publication cards must not gain review/due state.
        legacy_due = (
            db.scalar(
                select(func.count())
                .select_from(ReviewState)
                .where(ReviewState.card_id.in_(created_card_ids))
            )
            if created_card_ids
            else 0
        )
        if int(legacy_due or 0) != 0:
            db.rollback()
            raise InvalidRequestError(
                code="PUBLICATION_CREATED_REVIEW_STATE",
                message="publication import must not create review states",
                details={"review_states": int(legacy_due or 0)},
            )

        record = PublicationImport(
            publication_id=publication_id,
            manifest_hash=manifest_hash,
            package_hash=package_hash,
            schema_version=schema_version,
            status="imported",
            pipeline_version=pipeline_version or None,
            generation_version=generation_version or None,
            review_version=review_version or None,
            counts=validation.counts.model_dump(),
            stats=stats.model_dump(),
            conflicts=[],
            error_message=None,
            imported_at=timestamp,
            created_at=timestamp,
            updated_at=timestamp,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return _record_to_import_result(record, idempotent_replay=False)
    except InvalidRequestError:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise InvalidRequestError(
            code="PUBLICATION_IMPORT_CONFLICT",
            message="发布包导入与现有数据冲突",
            details={"error": str(exc.orig) if getattr(exc, "orig", None) else str(exc)},
        ) from exc
    except Exception:
        db.rollback()
        raise


def get_publication_status(db: Session, publication_id: str) -> PublicationStatusOut:
    row = db.scalar(
        select(PublicationImport)
        .where(PublicationImport.publication_id == publication_id)
        .limit(1)
    )
    if row is None:
        raise ResourceNotFoundError(
            code="PUBLICATION_NOT_FOUND",
            message="发布导入记录不存在",
            details={"publication_id": publication_id},
        )
    return _record_to_status(row)


__all__ = [
    "import_payload",
    "validate_publication_package",
    "import_publication_package",
    "get_publication_status",
    "load_publication_package",
]
