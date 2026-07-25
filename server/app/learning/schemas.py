from __future__ import annotations

import json
import math
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator

type AnswerScalar = str | int | float | bool | None


class EnrollmentStatus(StrEnum):
    QUEUED = "queued"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    RETIRED = "retired"


class EnrollmentSource(StrEnum):
    MANUAL = "manual"
    CHAPTER = "chapter"
    PLAN = "plan"


class EnrollmentScope(StrEnum):
    CARD = "card"
    CHAPTER = "chapter"
    BOOK = "book"


class EnrollmentCreate(BaseModel):
    user_id: int = Field(gt=0)
    card_id: int = Field(gt=0)
    priority: int = Field(default=50, ge=0, le=100)
    source: EnrollmentSource = EnrollmentSource.MANUAL


def _validate_enrollment_scope_target(
    *,
    scope: EnrollmentScope,
    card_id: int | None,
    chapter_id: int | None,
    book_id: int | None,
) -> None:
    targets = {
        EnrollmentScope.CARD: card_id,
        EnrollmentScope.CHAPTER: chapter_id,
        EnrollmentScope.BOOK: book_id,
    }
    provided = {
        EnrollmentScope.CARD: card_id is not None,
        EnrollmentScope.CHAPTER: chapter_id is not None,
        EnrollmentScope.BOOK: book_id is not None,
    }
    if sum(provided.values()) != 1:
        raise ValueError("provide exactly one of card_id, chapter_id, or book_id")
    if targets[scope] is None:
        raise ValueError(f"{scope.value}_id is required for scope={scope.value}")


class EnrollmentScopeCreate(BaseModel):
    user_id: int = Field(gt=0)
    scope: EnrollmentScope
    card_id: int | None = Field(default=None, gt=0)
    chapter_id: int | None = Field(default=None, gt=0)
    book_id: int | None = Field(default=None, gt=0)
    priority: int = Field(default=50, ge=0, le=100)

    @model_validator(mode="after")
    def require_matching_scope_target(self) -> EnrollmentScopeCreate:
        _validate_enrollment_scope_target(
            scope=self.scope,
            card_id=self.card_id,
            chapter_id=self.chapter_id,
            book_id=self.book_id,
        )
        return self


class EnrollmentRequest(BaseModel):
    scope: EnrollmentScope
    card_id: int | None = Field(default=None, gt=0)
    chapter_id: int | None = Field(default=None, gt=0)
    book_id: int | None = Field(default=None, gt=0)
    priority: int = Field(default=50, ge=0, le=100)

    @model_validator(mode="after")
    def require_matching_scope_target(self) -> EnrollmentRequest:
        _validate_enrollment_scope_target(
            scope=self.scope,
            card_id=self.card_id,
            chapter_id=self.chapter_id,
            book_id=self.book_id,
        )
        return self

    def to_scope_create(self, *, user_id: int) -> EnrollmentScopeCreate:
        return EnrollmentScopeCreate(
            user_id=user_id,
            scope=self.scope,
            card_id=self.card_id,
            chapter_id=self.chapter_id,
            book_id=self.book_id,
            priority=self.priority,
        )


class EnrollmentOut(BaseModel):
    id: int
    user_id: int
    card_id: int
    status: EnrollmentStatus
    priority: int
    source: EnrollmentSource
    introduced_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EnrollmentStatusUpdate(BaseModel):
    status: EnrollmentStatus

    @model_validator(mode="after")
    def require_mutable_status(self) -> EnrollmentStatusUpdate:
        if self.status == EnrollmentStatus.QUEUED:
            raise ValueError("queued is only entered through enrollment create")
        return self


class EnrollmentBatchOut(BaseModel):
    scope: EnrollmentScope
    created_count: int = Field(ge=0)
    existing_count: int = Field(ge=0)
    card_ids: list[int]
    enrollments: list[EnrollmentOut]


class StudySessionType(StrEnum):
    DAILY = "daily"
    FOCUSED = "focused"
    REVIEW = "review"
    ONBOARDING = "onboarding"


class StudySessionStatus(StrEnum):
    PLANNED = "planned"
    ACTIVE = "active"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"


class StudySessionCreate(BaseModel):
    user_id: int = Field(gt=0)
    session_type: StudySessionType = StudySessionType.DAILY
    estimated_minutes: int = Field(default=20, ge=0, le=1440)
    planned_task_count: int = Field(default=0, ge=0)


class StudySessionFinish(BaseModel):
    completed_task_count: int = Field(ge=0)
    actual_minutes: int = Field(ge=0, le=1440)


class ReviewStateValues(BaseModel):
    due_at: datetime
    stability: float = Field(ge=0, allow_inf_nan=False)
    difficulty: float = Field(ge=1, le=10, allow_inf_nan=False)
    elapsed_days: float = Field(ge=0, allow_inf_nan=False)
    scheduled_days: float = Field(ge=0, allow_inf_nan=False)
    reps: int = Field(ge=0)
    lapses: int = Field(ge=0)
    state: str = Field(pattern="^(new|learning|review|relearning)$")
    last_rating: int | None = Field(default=None, ge=1, le=4)
    last_reviewed_at: datetime | None = None
    algorithm_version: str = Field(min_length=1, max_length=32)

    @field_validator("algorithm_version")
    @classmethod
    def normalize_algorithm_version(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("algorithm_version must not be blank")
        return normalized


class ReviewAttemptCreate(BaseModel):
    user_id: int = Field(gt=0)
    session_id: int = Field(gt=0)
    card_id: int = Field(gt=0)
    card_revision: int = Field(gt=0)
    client_attempt_id: str = Field(min_length=1, max_length=128)
    rating: int = Field(ge=1, le=4)
    response_ms: int = Field(ge=0, le=86_400_000)
    hint_used: bool = False
    reveal_count: int = Field(default=0, ge=0, le=100)
    answer_payload: dict[str, AnswerScalar] | None = None
    next_state: ReviewStateValues

    @field_validator("client_attempt_id")
    @classmethod
    def normalize_client_attempt_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("client_attempt_id must not be blank")
        return normalized

    @field_validator("answer_payload")
    @classmethod
    def validate_answer_payload(
        cls, value: dict[str, AnswerScalar] | None
    ) -> dict[str, AnswerScalar] | None:
        if value is None:
            return None
        if len(value) > 16:
            raise ValueError("answer_payload supports at most 16 fields")
        normalized: dict[str, AnswerScalar] = {}
        for raw_key, item in value.items():
            key = raw_key.strip()
            if not key or len(key) > 64:
                raise ValueError("answer_payload keys must contain 1 to 64 characters")
            if key in normalized:
                raise ValueError("answer_payload keys must be unique after trimming")
            if isinstance(item, str) and len(item) > 4000:
                raise ValueError("answer_payload string values must not exceed 4000 characters")
            if isinstance(item, float) and not math.isfinite(item):
                raise ValueError("answer_payload numbers must be finite")
            normalized[key] = item
        encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 8192:
            raise ValueError("answer_payload must not exceed 8192 UTF-8 bytes")
        return normalized


class CardIssueType(StrEnum):
    FACT_ERROR = "fact_error"
    SOURCE_ERROR = "source_error"
    TOO_LARGE = "too_large"
    TOO_DIFFICULT = "too_difficult"
    UNCLEAR = "unclear"
    CONCEPT_CONFUSION = "concept_confusion"


class CardIssueStatus(StrEnum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class CardIssueCreate(BaseModel):
    user_id: int = Field(gt=0)
    card_id: int = Field(gt=0)
    card_revision: int = Field(gt=0)
    issue_type: CardIssueType
    details: str | None = Field(default=None, max_length=2000)

    @field_validator("details")
    @classmethod
    def normalize_details(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class CardIssueResolution(BaseModel):
    status: CardIssueStatus

    @model_validator(mode="after")
    def require_terminal_status(self) -> CardIssueResolution:
        if self.status not in {CardIssueStatus.RESOLVED, CardIssueStatus.DISMISSED}:
            raise ValueError("resolution status must be resolved or dismissed")
        return self
