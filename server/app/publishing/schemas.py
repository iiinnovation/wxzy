from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class CompatibilityCardImport(BaseModel):
    external_id: str | None = Field(default=None, max_length=128, validation_alias="id")
    book_name: str = Field(default="未命名", max_length=128, validation_alias="book")
    chapter: str | None = Field(default=None, max_length=128)
    section: str | None = Field(default=None, max_length=128)
    card_type: str = Field(default="other", min_length=1, max_length=64, validation_alias="type")
    question: str = Field(min_length=1, max_length=20_000)
    answer: str = Field(min_length=1, max_length=100_000)
    answer_points: list[str] = Field(default_factory=list, max_length=128)
    source_excerpt: str = Field(default="", max_length=100_000)
    source_pages: list[int] = Field(default_factory=list, max_length=1_000)
    tags: list[str] = Field(default_factory=list, max_length=128)
    status: str = Field(default="candidate", min_length=1, max_length=32)
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)

    model_config = {"extra": "ignore", "populate_by_name": True}

    @field_validator("book_name", mode="before")
    @classmethod
    def default_book_name(cls, value: object) -> object:
        return value if isinstance(value, str) and value.strip() else "未命名"

    @field_validator("card_type", mode="before")
    @classmethod
    def default_card_type(cls, value: object) -> object:
        return value if isinstance(value, str) and value.strip() else "other"

    @field_validator("status", mode="before")
    @classmethod
    def default_status(cls, value: object) -> object:
        return value if isinstance(value, str) and value.strip() else "candidate"

    @field_validator("source_excerpt", mode="before")
    @classmethod
    def default_source_excerpt(cls, value: object) -> object:
        return value if isinstance(value, str) else ""

    @field_validator("answer_points", "tags", mode="before")
    @classmethod
    def default_text_lists(cls, value: object) -> object:
        return value if isinstance(value, list) else []

    @field_validator("external_id", "chapter", "section")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("book_name", "card_type", "question", "answer", "status")
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

    @field_validator("source_pages", mode="before")
    @classmethod
    def normalize_source_pages(cls, value: object) -> object:
        if value is None:
            return []
        if not isinstance(value, list):
            return []
        pages: list[int] = []
        for item in value:
            if isinstance(item, bool):
                continue
            if isinstance(item, int) or (isinstance(item, str) and item.isdigit()):
                pages.append(int(item))
        return pages
