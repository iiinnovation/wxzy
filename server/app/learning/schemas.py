from __future__ import annotations

import json
import math
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator

from ..schemas import CardOut

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


class ChapterEnrollmentStatusUpdate(BaseModel):
    status: EnrollmentStatus

    @model_validator(mode="after")
    def require_pause_or_resume(self) -> ChapterEnrollmentStatusUpdate:
        if self.status not in {EnrollmentStatus.ACTIVE, EnrollmentStatus.SUSPENDED}:
            raise ValueError("chapter status supports only active or suspended")
        return self


class EnrollmentBatchOut(BaseModel):
    scope: EnrollmentScope
    created_count: int = Field(ge=0)
    existing_count: int = Field(ge=0)
    card_ids: list[int]
    enrollments: list[EnrollmentOut]


class ChapterEnrollmentStatusOut(BaseModel):
    chapter_id: int = Field(gt=0)
    status: EnrollmentStatus
    updated_count: int = Field(ge=0)
    unchanged_count: int = Field(ge=0)
    ignored_count: int = Field(ge=0)
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
    daily_plan_id: int | None = Field(default=None, gt=0)
    plan_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    cursor_position: int = Field(default=0, ge=0)


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
    # Optional optimistic concurrency checks against the locked CardReviewState.
    expected_due_at: datetime | None = None
    expected_state: str | None = Field(default=None, pattern="^(new|learning|review|relearning)$")
    expected_reps: int | None = Field(default=None, ge=0)

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


class ReviewAttemptRequest(BaseModel):
    session_id: int = Field(gt=0)
    card_id: int = Field(gt=0)
    card_revision: int = Field(gt=0)
    client_attempt_id: str = Field(min_length=1, max_length=128)
    rating: int = Field(ge=1, le=4)
    response_ms: int = Field(ge=0, le=86_400_000)
    hint_used: bool = False
    reveal_count: int = Field(default=0, ge=0, le=100)
    answer_payload: dict[str, AnswerScalar] | None = None
    expected_due_at: datetime | None = None
    expected_state: str | None = Field(default=None, pattern="^(new|learning|review|relearning)$")
    expected_reps: int | None = Field(default=None, ge=0)

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
        return ReviewAttemptCreate.validate_answer_payload(value)

    def to_create(self, *, user_id: int) -> ReviewAttemptCreate:
        return ReviewAttemptCreate(
            user_id=user_id,
            session_id=self.session_id,
            card_id=self.card_id,
            card_revision=self.card_revision,
            client_attempt_id=self.client_attempt_id,
            rating=self.rating,
            response_ms=self.response_ms,
            hint_used=self.hint_used,
            reveal_count=self.reveal_count,
            answer_payload=self.answer_payload,
            expected_due_at=self.expected_due_at,
            expected_state=self.expected_state,
            expected_reps=self.expected_reps,
        )


class ReviewAttemptOut(BaseModel):
    id: int
    session_id: int
    user_id: int
    card_id: int
    card_revision: int
    client_attempt_id: str
    rating: int
    response_ms: int
    hint_used: bool
    reveal_count: int
    answer_payload: dict[str, AnswerScalar] | None
    state_before: dict[str, object]
    state_after: dict[str, object]
    due_before: datetime
    due_after: datetime
    algorithm_version: str
    reviewed_at: datetime
    replayed: bool

    model_config = {"from_attributes": True}

    @classmethod
    def from_result(cls, result) -> ReviewAttemptOut:
        attempt = result.attempt
        return cls(
            id=attempt.id,
            session_id=attempt.session_id,
            user_id=attempt.user_id,
            card_id=attempt.card_id,
            card_revision=attempt.card_revision,
            client_attempt_id=attempt.client_attempt_id,
            rating=attempt.rating,
            response_ms=attempt.response_ms,
            hint_used=attempt.hint_used,
            reveal_count=attempt.reveal_count,
            answer_payload=attempt.answer_payload,
            state_before=dict(attempt.state_before),
            state_after=dict(attempt.state_after),
            due_before=attempt.due_before,
            due_after=attempt.due_after,
            algorithm_version=attempt.algorithm_version,
            reviewed_at=attempt.reviewed_at,
            replayed=result.replayed,
        )


class StudySessionRequest(BaseModel):
    session_type: StudySessionType = StudySessionType.DAILY
    estimated_minutes: int = Field(default=20, ge=0, le=1440)
    planned_task_count: int = Field(default=0, ge=0)
    auto_start: bool = True
    daily_plan_id: int | None = Field(default=None, gt=0)


class StudySessionOut(BaseModel):
    id: int
    user_id: int
    session_type: StudySessionType
    status: StudySessionStatus
    started_at: datetime | None
    ended_at: datetime | None
    estimated_minutes: int
    actual_minutes: int
    planned_task_count: int
    completed_task_count: int
    interruption_reason: str | None
    daily_plan_id: int | None
    plan_date: str | None
    cursor_position: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class StudySessionInterruptRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=512)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("reason must not be blank")
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


class DailyPlanItemType(StrEnum):
    DUE = "due"
    OVERDUE = "overdue"
    NEW = "new"
    WEAK_TOPIC = "weak_topic"
    REPAIR = "repair"
    MIXED_WEEKLY = "mixed_weekly"


class DailyPlanItemStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class DailyPlanItemOut(BaseModel):
    id: int
    position: int
    item_type: DailyPlanItemType
    enrollment_id: int
    card_id: int
    estimated_seconds: int
    reason_code: str
    reason_detail: str | None
    status: DailyPlanItemStatus

    model_config = {"from_attributes": True}


class DailyPlanOut(BaseModel):
    id: int
    user_id: int
    plan_date: str
    budget_minutes: int
    adjusted_budget_minutes: int | None
    effective_budget_minutes: int
    estimated_minutes: int
    due_count: int
    new_count: int
    weak_count: int
    generation_version: str
    is_initial: bool
    forecast_minutes_7d: int
    forecast_budget_7d: int
    new_cards_paused: bool
    pause_reasons: list[str]
    plan_reasons: list[str]
    generated_at: datetime
    created_at: datetime
    updated_at: datetime
    items: list[DailyPlanItemOut]

    model_config = {"from_attributes": True}

    @classmethod
    def from_plan(cls, plan: object) -> DailyPlanOut:
        adjusted = getattr(plan, "adjusted_budget_minutes")
        budget = getattr(plan, "budget_minutes")
        effective = int(adjusted if adjusted is not None else budget)
        items = [
            DailyPlanItemOut.model_validate(item, from_attributes=True)
            for item in sorted(getattr(plan, "items", []), key=lambda row: row.position)
        ]
        return cls(
            id=getattr(plan, "id"),
            user_id=getattr(plan, "user_id"),
            plan_date=getattr(plan, "plan_date"),
            budget_minutes=budget,
            adjusted_budget_minutes=adjusted,
            effective_budget_minutes=effective,
            estimated_minutes=getattr(plan, "estimated_minutes"),
            due_count=getattr(plan, "due_count"),
            new_count=getattr(plan, "new_count"),
            weak_count=getattr(plan, "weak_count"),
            generation_version=getattr(plan, "generation_version"),
            is_initial=bool(getattr(plan, "is_initial")),
            forecast_minutes_7d=getattr(plan, "forecast_minutes_7d"),
            forecast_budget_7d=getattr(plan, "forecast_budget_7d"),
            new_cards_paused=bool(getattr(plan, "new_cards_paused")),
            pause_reasons=list(getattr(plan, "pause_reasons") or []),
            plan_reasons=list(getattr(plan, "plan_reasons") or []),
            generated_at=getattr(plan, "generated_at"),
            created_at=getattr(plan, "created_at"),
            updated_at=getattr(plan, "updated_at"),
            items=items,
        )


class DailyPlanBudgetAdjust(BaseModel):
    budget_minutes: int = Field(ge=5, le=240)


class StudySessionTaskOut(BaseModel):
    plan_item: DailyPlanItemOut
    card: CardOut
    card_revision: int = Field(gt=0)
    review_state: ReviewStateValues


class StudySessionNextOut(BaseModel):
    session: StudySessionOut
    task: StudySessionTaskOut | None


class RepairSignalCode(StrEnum):
    REPEATED_AGAIN = "repeated_again"
    SLOW_HARD = "slow_hard"
    TAG_CONFUSION = "tag_confusion"
    CARD_ISSUE = "card_issue"


class RepairActionCode(StrEnum):
    REREAD_SOURCE = "reread_source"
    WRITTEN_RECALL = "written_recall"
    COMPARE_CARDS = "compare_cards"
    SPLIT_CARD = "split_card"
    REVIEW_CONTENT = "review_content"


class RepairSignalOut(BaseModel):
    code: RepairSignalCode
    detail: str


class RepairActionOut(BaseModel):
    code: RepairActionCode
    reason: str


class RepairEvidenceOut(BaseModel):
    attempt_count: int = Field(ge=0)
    again_count: int = Field(ge=0)
    hard_count: int = Field(ge=0)
    slow_hard_count: int = Field(ge=0)
    issue_types: list[CardIssueType]
    confusion_tags: list[str]
    related_card_ids: list[int]
    latest_failure_at: datetime | None


class RepairSourceOut(BaseModel):
    card_id: int
    card_revision: int = Field(gt=0)
    book_id: int
    book_name: str
    subject: str | None
    chapter: str | None
    section: str | None
    source_id: int | None
    excerpt: str
    pdf_page_start: int | None
    pdf_page_end: int | None
    printed_page_start_label: str | None
    printed_page_end_label: str | None


class RepairSuggestionOut(BaseModel):
    card_id: int
    card_revision: int = Field(gt=0)
    topic: str
    tags: list[str]
    severity_score: int = Field(ge=0)
    reason_code: str
    reason_detail: str
    signals: list[RepairSignalOut]
    actions: list[RepairActionOut]
    evidence: RepairEvidenceOut
    source: RepairSourceOut


class RepairSuggestionListOut(BaseModel):
    user_id: int
    lookback_days: int = Field(gt=0)
    generated_at: datetime
    items: list[RepairSuggestionOut]


class InsightContentProgressOut(BaseModel):
    document_page_count: int = Field(ge=0)
    covered_page_count: int = Field(ge=0)
    coverage_ratio: float = Field(ge=0, le=1)
    published_card_count: int = Field(ge=0)
    enrolled_card_count: int = Field(ge=0)
    active_card_count: int = Field(ge=0)
    mastered_card_count: int = Field(ge=0)


class InsightSubjectTrendOut(BaseModel):
    subject: str
    published_card_count: int = Field(ge=0)
    enrolled_card_count: int = Field(ge=0)
    active_card_count: int = Field(ge=0)
    mastered_card_count: int = Field(ge=0)
    attempt_count_30d: int = Field(ge=0)
    again_count_30d: int = Field(ge=0)
    hard_count_30d: int = Field(ge=0)
    success_rate_30d: float | None = Field(default=None, ge=0, le=1)
    trend: str = Field(pattern="^(insufficient|improving|stable|declining)$")


class InsightSummaryOut(BaseModel):
    user_id: int
    timezone: str
    local_date: str
    generated_at: datetime
    study_days: int = Field(ge=0)
    total_actual_minutes: int = Field(ge=0)
    total_review_count: int = Field(ge=0)
    total_new_count: int = Field(ge=0)
    today_actual_minutes: int = Field(ge=0)
    today_review_count: int = Field(ge=0)
    today_new_count: int = Field(ge=0)
    current_due_count: int = Field(ge=0)
    backlog_count: int = Field(ge=0)
    content: InsightContentProgressOut
    subjects: list[InsightSubjectTrendOut]


class InsightWorkloadDayOut(BaseModel):
    local_date: str
    due_count: int = Field(ge=0)
    overdue_count: int = Field(ge=0)
    estimated_minutes: int = Field(ge=0)
    budget_minutes: int = Field(ge=0)
    overloaded: bool


class InsightWorkloadOut(BaseModel):
    user_id: int
    timezone: str
    generated_at: datetime
    review_seconds_estimate: int = Field(gt=0)
    total_due_count: int = Field(ge=0)
    total_estimated_minutes: int = Field(ge=0)
    total_budget_minutes: int = Field(ge=0)
    overloaded: bool
    days: list[InsightWorkloadDayOut]


class InsightWeakTopicPageOut(BaseModel):
    user_id: int
    generated_at: datetime
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(gt=0)
    has_more: bool
    items: list[RepairSuggestionOut]
