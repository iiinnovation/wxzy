from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-fA-F]{64}$")]


class CopyrightScope(StrEnum):
    PERSONAL_USE = "personal_use"
    LICENSED = "licensed"
    PUBLIC_DOMAIN = "public_domain"


class DocumentVersionStatus(StrEnum):
    REGISTERED = "registered"
    SPLIT = "split"
    PARSING = "parsing"
    PARSED = "parsed"
    CLEANING = "cleaning"
    STRUCTURED = "structured"
    QUALITY_REVIEW = "quality_review"
    NEEDS_REVIEW = "needs_review"
    READY_FOR_GENERATION = "ready_for_generation"
    PUBLISHED = "published"
    FAILED = "failed"
    RETRYING = "retrying"


class ChunkQualityStatus(StrEnum):
    READY = "ready"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class DocumentCreate(BaseModel):
    document_key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    title: str = Field(min_length=1, max_length=256)
    subject: str | None = Field(default=None, max_length=128)
    edition_note: str | None = Field(default=None, max_length=256)
    copyright_scope: CopyrightScope = CopyrightScope.PERSONAL_USE
    copyright_notice: str | None = Field(default=None, max_length=512)

    @field_validator("document_key", mode="before")
    @classmethod
    def normalize_document_key(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("title must not be blank")
        return normalized

    @field_validator("subject", "edition_note", "copyright_notice")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class DocumentVersionCreate(BaseModel):
    source_sha256: Sha256
    source_file_name: str = Field(min_length=1, max_length=256)
    page_count: int = Field(gt=0, le=100_000)
    size_bytes: int = Field(gt=0)
    processing_version: str = Field(min_length=1, max_length=64)
    status: DocumentVersionStatus = DocumentVersionStatus.REGISTERED

    @field_validator("source_sha256")
    @classmethod
    def normalize_sha256(cls, value: str) -> str:
        return value.lower()

    @field_validator("source_file_name")
    @classmethod
    def reject_source_paths(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or "/" in normalized or "\\" in normalized or "\x00" in normalized:
            raise ValueError("source_file_name must be a file name without a path")
        return normalized

    @field_validator("processing_version")
    @classmethod
    def normalize_processing_version(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("processing_version must not be blank")
        return normalized


class ChapterCreate(BaseModel):
    document_version_id: int = Field(gt=0)
    parent_id: int | None = Field(default=None, gt=0)
    chapter_key: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=256)
    level: int = Field(ge=0, le=32)
    sort_order: int = Field(ge=0)
    pdf_page_index_start: int = Field(ge=0)
    pdf_page_index_end: int = Field(ge=0)
    printed_page_start_label: str | None = Field(default=None, max_length=32)
    printed_page_end_label: str | None = Field(default=None, max_length=32)
    recognition_method: str = Field(min_length=1, max_length=64)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator("chapter_key", "title", "recognition_method")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("text values must not be blank")
        return normalized

    @field_validator("printed_page_start_label", "printed_page_end_label")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_page_range(self) -> ChapterCreate:
        if self.pdf_page_index_end < self.pdf_page_index_start:
            raise ValueError("pdf_page_index_end must not precede pdf_page_index_start")
        return self


class DocumentChunkCreate(BaseModel):
    document_version_id: int = Field(gt=0)
    chapter_id: int | None = Field(default=None, gt=0)
    chunk_key: str = Field(min_length=1, max_length=128)
    chapter_path: list[str] = Field(default_factory=list, max_length=32)
    pdf_page_index_start: int = Field(ge=0)
    pdf_page_index_end: int = Field(ge=0)
    printed_page_labels: list[str] = Field(default_factory=list, max_length=128)
    block_type: str = Field(min_length=1, max_length=64)
    source_text: str = Field(min_length=1)
    cleaned_text: str = Field(min_length=1)
    content_hash: Sha256
    quality_status: ChunkQualityStatus
    quality_flags: list[str] = Field(default_factory=list, max_length=128)
    pipeline_version: str = Field(min_length=1, max_length=64)

    @field_validator("content_hash")
    @classmethod
    def normalize_content_hash(cls, value: str) -> str:
        return value.lower()

    @field_validator("chunk_key", "block_type", "pipeline_version")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("text values must not be blank")
        return normalized

    @field_validator("source_text", "cleaned_text")
    @classmethod
    def validate_content_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content text must not be blank")
        return value

    @field_validator("chapter_path", "printed_page_labels", "quality_flags")
    @classmethod
    def normalize_text_list(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            text = item.strip()
            if not text:
                raise ValueError("list values must not be blank")
            if len(text) > 256:
                raise ValueError("list values must not exceed 256 characters")
            normalized.append(text)
        return normalized

    @model_validator(mode="after")
    def validate_page_range(self) -> DocumentChunkCreate:
        if self.pdf_page_index_end < self.pdf_page_index_start:
            raise ValueError("pdf_page_index_end must not precede pdf_page_index_start")
        return self


class CardSourceCreate(BaseModel):
    document_chunk_id: int = Field(gt=0)
    citation_order: int = Field(ge=0)
    excerpt: str = Field(min_length=1, max_length=4_000)
    pdf_page_index_start: int = Field(ge=0)
    pdf_page_index_end: int = Field(ge=0)
    printed_page_start_label: str | None = Field(default=None, max_length=32)
    printed_page_end_label: str | None = Field(default=None, max_length=32)

    @field_validator("excerpt")
    @classmethod
    def normalize_excerpt(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("excerpt must not be blank")
        return normalized

    @field_validator("printed_page_start_label", "printed_page_end_label")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_page_range(self) -> CardSourceCreate:
        if self.pdf_page_index_end < self.pdf_page_index_start:
            raise ValueError("pdf_page_index_end must not precede pdf_page_index_start")
        return self


class CatalogCardCreate(BaseModel):
    external_id: str = Field(min_length=1, max_length=128)
    book_id: int = Field(gt=0)
    content_revision: int = Field(default=1, ge=1)
    content_hash: Sha256
    card_type: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1, max_length=2_000)
    answer: str = Field(min_length=1, max_length=20_000)
    answer_points: list[str] = Field(default_factory=list, max_length=128)
    tags: list[str] = Field(default_factory=list, max_length=128)
    sources: list[CardSourceCreate] = Field(min_length=1, max_length=64)

    @field_validator("content_hash")
    @classmethod
    def normalize_content_hash(cls, value: str) -> str:
        return value.lower()

    @field_validator("external_id", "card_type", "question", "answer")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("text values must not be blank")
        return normalized

    @field_validator("answer_points", "tags")
    @classmethod
    def normalize_text_list(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            text = item.strip()
            if not text:
                raise ValueError("list values must not be blank")
            if len(text) > 512:
                raise ValueError("list values must not exceed 512 characters")
            normalized.append(text)
        return normalized

    @model_validator(mode="after")
    def validate_source_identity(self) -> CatalogCardCreate:
        orders = sorted(source.citation_order for source in self.sources)
        if orders != list(range(len(self.sources))):
            raise ValueError("citation_order must be contiguous and start at zero")
        chunk_ids = [source.document_chunk_id for source in self.sources]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("a card must not cite the same chunk more than once")
        return self


class CardSourceOut(BaseModel):
    id: int
    card_id: int
    citation_order: int
    document_key: str
    document_title: str
    document_version_id: int
    chunk_key: str
    chapter_path: list[str]
    excerpt: str
    pdf_page_index_start: int
    pdf_page_index_end: int
    pdf_page_number_start: int
    pdf_page_number_end: int
    printed_page_start_label: str | None
    printed_page_end_label: str | None
