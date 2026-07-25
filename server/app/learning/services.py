from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic, sleep

from sqlalchemy import and_, case, func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from ..catalog.models import Book, Card, CardSource, Chapter, DocumentChunk
from ..catalog.services import card_to_out
from ..config import get_settings
from ..core.errors import ResourceNotFoundError
from ..identity.models import User
from ..models import ReviewLog, ReviewState
from ..schemas import ReviewAnswerOut, ReviewDueItem, StatsOut
from .fsrs_adapter import ALGORITHM_VERSION, schedule, utcnow
from .models import CardEnrollment, CardIssue, CardReviewState, ReviewAttempt, StudySession
from .schemas import (
    CardIssueCreate,
    CardIssueResolution,
    EnrollmentCreate,
    EnrollmentScope,
    EnrollmentScopeCreate,
    EnrollmentSource,
    EnrollmentStatus,
    ReviewAttemptCreate,
    ReviewStateValues,
    StudySessionCreate,
    StudySessionFinish,
    StudySessionStatus,
)


class EnrollmentReferenceError(RuntimeError):
    pass


class EnrollmentStateError(RuntimeError):
    pass


class StudySessionReferenceError(RuntimeError):
    pass


class StudySessionStateError(RuntimeError):
    pass


class ReviewAttemptReferenceError(RuntimeError):
    pass


class ReviewAttemptConflictError(RuntimeError):
    pass


class CardIssueReferenceError(RuntimeError):
    pass


class CardIssueStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class EnrollmentResult:
    enrollment: CardEnrollment
    created: bool


@dataclass(frozen=True)
class BulkEnrollmentResult:
    scope: EnrollmentScope
    enrollments: list[CardEnrollment]
    created_count: int
    existing_count: int
    card_ids: list[int]


@dataclass(frozen=True)
class IntroductionResult:
    enrollment: CardEnrollment
    review_state: CardReviewState
    state_created: bool


@dataclass(frozen=True)
class ReviewAttemptResult:
    attempt: ReviewAttempt
    replayed: bool


def ensure_review_state(db: Session, card: Card) -> ReviewState:
    if card.review_state:
        return card.review_state
    review_state = ReviewState(
        card_id=card.id,
        due_at=utcnow(),
        stability=1.0,
        difficulty=5.0,
        state="new",
        algorithm_version=get_settings().algorithm_version,
    )
    db.add(review_state)
    db.flush()
    return review_state


def list_due(db: Session, *, limit: int = 30) -> list[ReviewDueItem]:
    now = utcnow()
    states = db.scalars(
        select(ReviewState)
        .join(Card)
        .where(Card.status == "approved", ReviewState.due_at <= now)
        .order_by(ReviewState.due_at.asc())
        .limit(min(limit, 100))
    ).all()
    return [
        ReviewDueItem(
            card=card_to_out(state.card),
            due_at=state.due_at,
            state=state.state,
            reps=state.reps,
            lapses=state.lapses,
            stability=state.stability,
            difficulty=state.difficulty,
        )
        for state in states
    ]


def answer_review(db: Session, *, card_id: int, rating: int) -> ReviewAnswerOut:
    card = db.get(Card, card_id)
    if card is None or card.status != "approved":
        raise ResourceNotFoundError(
            code="CARD_NOT_FOUND",
            message="卡片不存在或尚未发布",
        )
    try:
        state = ensure_review_state(db, card)
        before_due = state.due_at
        before_state = state.state
        reviewed_at = utcnow()
        result = schedule(
            rating=rating,
            now=reviewed_at,
            stability=state.stability,
            difficulty=state.difficulty,
            reps=state.reps,
            lapses=state.lapses,
            state=state.state,
            last_reviewed_at=state.last_reviewed_at,
        )
        state.due_at = result.due_at
        state.stability = result.stability
        state.difficulty = result.difficulty
        state.elapsed_days = result.elapsed_days
        state.scheduled_days = result.scheduled_days
        state.reps = result.reps
        state.lapses = result.lapses
        state.state = result.state
        state.last_rating = rating
        state.last_reviewed_at = reviewed_at
        state.algorithm_version = get_settings().algorithm_version
        db.add(
            ReviewLog(
                card_id=card.id,
                rating=rating,
                due_before=before_due,
                due_after=result.due_at,
                stability_after=result.stability,
                difficulty_after=result.difficulty,
                algorithm_version=state.algorithm_version,
                state_before=before_state,
                state_after=result.state,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(state)
    return ReviewAnswerOut(
        card_id=card.id,
        rating=rating,
        due_at=state.due_at,
        scheduled_days=state.scheduled_days,
        stability=state.stability,
        difficulty=state.difficulty,
        state=state.state,
        reps=state.reps,
        lapses=state.lapses,
        algorithm_version=state.algorithm_version,
    )


def stats(db: Session) -> StatsOut:
    now = utcnow()
    start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    books = db.scalar(select(func.count()).select_from(Book)) or 0
    approved = (
        db.scalar(select(func.count()).select_from(Card).where(Card.status == "approved")) or 0
    )
    due = (
        db.scalar(
            select(func.count())
            .select_from(ReviewState)
            .join(Card)
            .where(Card.status == "approved", ReviewState.due_at <= now)
        )
        or 0
    )
    reviewed_today = (
        db.scalar(select(func.count()).select_from(ReviewLog).where(ReviewLog.reviewed_at >= start))
        or 0
    )
    new_cards = (
        db.scalar(
            select(func.count())
            .select_from(ReviewState)
            .join(Card)
            .where(Card.status == "approved", ReviewState.state == "new")
        )
        or 0
    )
    return StatsOut(
        books=int(books),
        cards_approved=int(approved),
        due_now=int(due),
        reviewed_today=int(reviewed_today),
        new_cards=int(new_cards),
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime values must include a timezone")
    return value.astimezone(UTC)


def _eligible_user_and_card(db: Session, *, user_id: int, card_id: int) -> tuple[User, Card]:
    user = db.get(User, user_id)
    if user is None or user.status != "active":
        raise EnrollmentReferenceError("an active Owner is required")
    card = db.get(Card, card_id)
    if card is None or card.status not in {"approved", "published"}:
        raise EnrollmentReferenceError("only approved or published cards can be enrolled")
    return user, card


def enroll_card(
    db: Session, values: EnrollmentCreate, *, now: datetime | None = None
) -> EnrollmentResult:
    _eligible_user_and_card(db, user_id=values.user_id, card_id=values.card_id)
    timestamp = _require_aware_utc(now or _utc_now())
    existing = db.scalar(
        select(CardEnrollment)
        .where(
            CardEnrollment.user_id == values.user_id,
            CardEnrollment.card_id == values.card_id,
        )
        .limit(1)
    )
    if existing is not None:
        return EnrollmentResult(enrollment=existing, created=False)

    enrollment = CardEnrollment(
        user_id=values.user_id,
        card_id=values.card_id,
        status=EnrollmentStatus.QUEUED.value,
        priority=values.priority,
        source=values.source.value,
        created_at=timestamp,
        updated_at=timestamp,
    )
    db.add(enrollment)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(
            select(CardEnrollment)
            .where(
                CardEnrollment.user_id == values.user_id,
                CardEnrollment.card_id == values.card_id,
            )
            .limit(1)
        )
        if existing is not None:
            return EnrollmentResult(enrollment=existing, created=False)
        raise EnrollmentStateError("enrollment conflicts with existing data") from exc
    db.refresh(enrollment)
    return EnrollmentResult(enrollment=enrollment, created=True)


def _require_active_user(db: Session, *, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None or user.status != "active":
        raise EnrollmentReferenceError("an active Owner is required")
    return user


def _eligible_card_statuses() -> tuple[str, ...]:
    return ("approved", "published")


def _chapter_subtree_ids(db: Session, *, root_chapter_id: int) -> list[int]:
    root = db.get(Chapter, root_chapter_id)
    if root is None:
        raise EnrollmentReferenceError("chapter does not exist")

    children_by_parent: dict[int | None, list[Chapter]] = {}
    for chapter in db.scalars(
        select(Chapter)
        .where(Chapter.document_version_id == root.document_version_id)
        .order_by(Chapter.sort_order, Chapter.id)
    ):
        children_by_parent.setdefault(chapter.parent_id, []).append(chapter)

    ordered_ids: list[int] = []
    stack = [root]
    while stack:
        current = stack.pop()
        ordered_ids.append(current.id)
        children = children_by_parent.get(current.id, [])
        # reverse so lower sort_order is processed first with stack
        for child in reversed(children):
            stack.append(child)
    return ordered_ids


def list_enrollable_card_ids_for_chapter(db: Session, *, chapter_id: int) -> list[int]:
    chapter_ids = _chapter_subtree_ids(db, root_chapter_id=chapter_id)
    rows = db.execute(
        select(
            Card.id,
            func.min(Chapter.sort_order).label("chapter_sort"),
            func.min(DocumentChunk.pdf_page_index_start).label("page_start"),
            func.min(CardSource.citation_order).label("citation_order"),
        )
        .select_from(Card)
        .join(CardSource, CardSource.card_id == Card.id)
        .join(DocumentChunk, DocumentChunk.id == CardSource.document_chunk_id)
        .join(Chapter, Chapter.id == DocumentChunk.chapter_id)
        .where(
            DocumentChunk.chapter_id.in_(chapter_ids),
            Card.status.in_(_eligible_card_statuses()),
        )
        .group_by(Card.id)
        .order_by(
            func.min(Chapter.sort_order),
            func.min(DocumentChunk.pdf_page_index_start),
            func.min(CardSource.citation_order),
            Card.id,
        )
    ).all()
    return [int(row.id) for row in rows]


def list_enrollable_card_ids_for_book(db: Session, *, book_id: int) -> list[int]:
    book = db.get(Book, book_id)
    if book is None:
        raise EnrollmentReferenceError("book does not exist")

    chapter_sort = func.min(Chapter.sort_order)
    page_start = func.min(DocumentChunk.pdf_page_index_start)
    citation_order = func.min(CardSource.citation_order)
    rows = db.execute(
        select(
            Card.id,
            chapter_sort.label("chapter_sort"),
            page_start.label("page_start"),
            citation_order.label("citation_order"),
        )
        .select_from(Card)
        .outerjoin(CardSource, CardSource.card_id == Card.id)
        .outerjoin(DocumentChunk, DocumentChunk.id == CardSource.document_chunk_id)
        .outerjoin(Chapter, Chapter.id == DocumentChunk.chapter_id)
        .where(
            Card.book_id == book_id,
            Card.status.in_(_eligible_card_statuses()),
        )
        .group_by(Card.id)
        .order_by(
            case((chapter_sort.is_(None), 1), else_=0),
            chapter_sort,
            case((page_start.is_(None), 1), else_=0),
            page_start,
            case((citation_order.is_(None), 1), else_=0),
            citation_order,
            Card.id,
        )
    ).all()
    return [int(row.id) for row in rows]


def _enroll_card_ids(
    db: Session,
    *,
    user_id: int,
    card_ids: list[int],
    priority: int,
    source: EnrollmentSource,
    scope: EnrollmentScope,
    now: datetime | None = None,
) -> BulkEnrollmentResult:
    _require_active_user(db, user_id=user_id)
    timestamp = _require_aware_utc(now or _utc_now())
    ordered_ids = list(dict.fromkeys(card_ids))
    if not ordered_ids:
        return BulkEnrollmentResult(
            scope=scope,
            enrollments=[],
            created_count=0,
            existing_count=0,
            card_ids=[],
        )

    cards = list(
        db.scalars(
            select(Card).where(
                Card.id.in_(ordered_ids),
                Card.status.in_(_eligible_card_statuses()),
            )
        )
    )
    cards_by_id = {card.id: card for card in cards}
    missing = [card_id for card_id in ordered_ids if card_id not in cards_by_id]
    if missing:
        raise EnrollmentReferenceError("only approved or published cards can be enrolled")

    existing_rows = list(
        db.scalars(
            select(CardEnrollment).where(
                CardEnrollment.user_id == user_id,
                CardEnrollment.card_id.in_(ordered_ids),
            )
        )
    )
    existing_by_card = {row.card_id: row for row in existing_rows}
    created_count = 0
    for card_id in ordered_ids:
        if card_id in existing_by_card:
            continue
        enrollment = CardEnrollment(
            user_id=user_id,
            card_id=card_id,
            status=EnrollmentStatus.QUEUED.value,
            priority=priority,
            source=source.value,
            created_at=timestamp,
            updated_at=timestamp,
        )
        db.add(enrollment)
        existing_by_card[card_id] = enrollment
        created_count += 1

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing_rows = list(
            db.scalars(
                select(CardEnrollment).where(
                    CardEnrollment.user_id == user_id,
                    CardEnrollment.card_id.in_(ordered_ids),
                )
            )
        )
        existing_by_card = {row.card_id: row for row in existing_rows}
        missing_after = [card_id for card_id in ordered_ids if card_id not in existing_by_card]
        if missing_after:
            raise EnrollmentStateError("enrollment conflicts with existing data") from exc
        created_count = 0

    enrollments: list[CardEnrollment] = []
    for card_id in ordered_ids:
        enrollment = existing_by_card[card_id]
        db.refresh(enrollment)
        enrollments.append(enrollment)

    existing_count = len(ordered_ids) - created_count
    return BulkEnrollmentResult(
        scope=scope,
        enrollments=enrollments,
        created_count=created_count,
        existing_count=existing_count,
        card_ids=ordered_ids,
    )


def enroll_chapter(
    db: Session,
    *,
    user_id: int,
    chapter_id: int,
    priority: int = 50,
    now: datetime | None = None,
) -> BulkEnrollmentResult:
    card_ids = list_enrollable_card_ids_for_chapter(db, chapter_id=chapter_id)
    return _enroll_card_ids(
        db,
        user_id=user_id,
        card_ids=card_ids,
        priority=priority,
        source=EnrollmentSource.CHAPTER,
        scope=EnrollmentScope.CHAPTER,
        now=now,
    )


def enroll_book(
    db: Session,
    *,
    user_id: int,
    book_id: int,
    priority: int = 50,
    now: datetime | None = None,
) -> BulkEnrollmentResult:
    card_ids = list_enrollable_card_ids_for_book(db, book_id=book_id)
    return _enroll_card_ids(
        db,
        user_id=user_id,
        card_ids=card_ids,
        priority=priority,
        source=EnrollmentSource.CHAPTER,
        scope=EnrollmentScope.BOOK,
        now=now,
    )


def enroll_scope(
    db: Session, values: EnrollmentScopeCreate, *, now: datetime | None = None
) -> BulkEnrollmentResult:
    if values.scope == EnrollmentScope.CARD:
        assert values.card_id is not None
        result = enroll_card(
            db,
            EnrollmentCreate(
                user_id=values.user_id,
                card_id=values.card_id,
                priority=values.priority,
                source=EnrollmentSource.MANUAL,
            ),
            now=now,
        )
        return BulkEnrollmentResult(
            scope=EnrollmentScope.CARD,
            enrollments=[result.enrollment],
            created_count=1 if result.created else 0,
            existing_count=0 if result.created else 1,
            card_ids=[result.enrollment.card_id],
        )
    if values.scope == EnrollmentScope.CHAPTER:
        assert values.chapter_id is not None
        return enroll_chapter(
            db,
            user_id=values.user_id,
            chapter_id=values.chapter_id,
            priority=values.priority,
            now=now,
        )
    assert values.book_id is not None
    return enroll_book(
        db,
        user_id=values.user_id,
        book_id=values.book_id,
        priority=values.priority,
        now=now,
    )


def list_queued_enrollments(
    db: Session,
    *,
    user_id: int,
    limit: int = 100,
) -> list[CardEnrollment]:
    """Return queued enrollments in introduction order: priority, chapter, card."""
    _require_active_user(db, user_id=user_id)
    chapter_sort = func.min(Chapter.sort_order)
    page_start = func.min(DocumentChunk.pdf_page_index_start)
    return list(
        db.scalars(
            select(CardEnrollment)
            .join(Card, Card.id == CardEnrollment.card_id)
            .outerjoin(CardSource, CardSource.card_id == Card.id)
            .outerjoin(DocumentChunk, DocumentChunk.id == CardSource.document_chunk_id)
            .outerjoin(Chapter, Chapter.id == DocumentChunk.chapter_id)
            .where(
                CardEnrollment.user_id == user_id,
                CardEnrollment.status == EnrollmentStatus.QUEUED.value,
                Card.status.in_(_eligible_card_statuses()),
            )
            .group_by(CardEnrollment.id)
            .order_by(
                CardEnrollment.priority.desc(),
                case((chapter_sort.is_(None), 1), else_=0),
                chapter_sort,
                case((page_start.is_(None), 1), else_=0),
                page_start,
                CardEnrollment.card_id,
                CardEnrollment.id,
            )
            .limit(min(max(limit, 1), 500))
        )
    )


def introduce_enrollment(
    db: Session,
    *,
    enrollment_id: int,
    algorithm_version: str = ALGORITHM_VERSION,
    now: datetime | None = None,
) -> IntroductionResult:
    enrollment = db.get(CardEnrollment, enrollment_id)
    if enrollment is None:
        raise EnrollmentReferenceError("enrollment does not exist")
    if enrollment.status in {EnrollmentStatus.SUSPENDED.value, EnrollmentStatus.RETIRED.value}:
        raise EnrollmentStateError("suspended or retired enrollment cannot be introduced")
    _eligible_user_and_card(db, user_id=enrollment.user_id, card_id=enrollment.card_id)
    algorithm_version = algorithm_version.strip()
    if not algorithm_version or len(algorithm_version) > 32:
        raise EnrollmentStateError("algorithm_version must contain 1 to 32 characters")
    timestamp = _require_aware_utc(now or _utc_now())
    state = db.scalar(
        select(CardReviewState)
        .where(
            CardReviewState.user_id == enrollment.user_id,
            CardReviewState.card_id == enrollment.card_id,
        )
        .limit(1)
    )
    state_created = state is None
    if state is None:
        state = CardReviewState(
            user_id=enrollment.user_id,
            card_id=enrollment.card_id,
            due_at=timestamp,
            stability=1.0,
            difficulty=5.0,
            elapsed_days=0.0,
            scheduled_days=0.0,
            reps=0,
            lapses=0,
            state="new",
            algorithm_version=algorithm_version,
            created_at=timestamp,
            updated_at=timestamp,
        )
        db.add(state)

    enrollment.status = EnrollmentStatus.ACTIVE.value
    if enrollment.introduced_at is None:
        enrollment.introduced_at = timestamp
    enrollment.updated_at = timestamp
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        enrollment = db.get(CardEnrollment, enrollment_id)
        if enrollment is None:
            raise EnrollmentStateError("enrollment disappeared during introduction") from exc
        state = db.scalar(
            select(CardReviewState)
            .where(
                CardReviewState.user_id == enrollment.user_id,
                CardReviewState.card_id == enrollment.card_id,
            )
            .limit(1)
        )
        if state is None:
            raise EnrollmentStateError("review state conflicts with existing data") from exc
        return IntroductionResult(enrollment=enrollment, review_state=state, state_created=False)
    db.refresh(enrollment)
    db.refresh(state)
    return IntroductionResult(
        enrollment=enrollment,
        review_state=state,
        state_created=state_created,
    )


def change_enrollment_status(
    db: Session,
    *,
    enrollment_id: int,
    target_status: EnrollmentStatus,
    now: datetime | None = None,
) -> CardEnrollment:
    enrollment = db.get(CardEnrollment, enrollment_id)
    if enrollment is None:
        raise EnrollmentReferenceError("enrollment does not exist")
    if enrollment.status == target_status.value:
        return enrollment
    if target_status == EnrollmentStatus.QUEUED:
        raise EnrollmentStateError("queued is only entered through enroll_card")
    if target_status == EnrollmentStatus.SUSPENDED and enrollment.status != EnrollmentStatus.ACTIVE:
        raise EnrollmentStateError("only an active enrollment can be suspended")
    if target_status == EnrollmentStatus.ACTIVE:
        if enrollment.status != EnrollmentStatus.SUSPENDED.value:
            raise EnrollmentStateError("only a suspended enrollment can be resumed")
        state_id = db.scalar(
            select(CardReviewState.id).where(
                CardReviewState.user_id == enrollment.user_id,
                CardReviewState.card_id == enrollment.card_id,
            )
        )
        if state_id is None:
            raise EnrollmentStateError("introduce the enrollment before activating it")
    if target_status == EnrollmentStatus.RETIRED and enrollment.status not in {
        EnrollmentStatus.QUEUED.value,
        EnrollmentStatus.ACTIVE.value,
        EnrollmentStatus.SUSPENDED.value,
    }:
        raise EnrollmentStateError("enrollment cannot transition to retired")
    enrollment.status = target_status.value
    enrollment.updated_at = _require_aware_utc(now or _utc_now())
    db.commit()
    db.refresh(enrollment)
    return enrollment


def list_due_review_states(
    db: Session,
    *,
    user_id: int,
    now: datetime | None = None,
    limit: int = 100,
) -> list[CardReviewState]:
    timestamp = _require_aware_utc(now or _utc_now())
    return list(
        db.scalars(
            select(CardReviewState)
            .join(
                CardEnrollment,
                and_(
                    CardEnrollment.user_id == CardReviewState.user_id,
                    CardEnrollment.card_id == CardReviewState.card_id,
                ),
            )
            .join(Card, Card.id == CardReviewState.card_id)
            .join(User, User.id == CardReviewState.user_id)
            .where(
                CardReviewState.user_id == user_id,
                CardReviewState.due_at <= timestamp,
                CardEnrollment.status == EnrollmentStatus.ACTIVE.value,
                Card.status.in_(("approved", "published")),
                User.status == "active",
            )
            .order_by(CardReviewState.due_at, CardReviewState.id)
            .limit(min(max(limit, 1), 500))
        )
    )


def create_study_session(
    db: Session, values: StudySessionCreate, *, now: datetime | None = None
) -> StudySession:
    user = db.get(User, values.user_id)
    if user is None or user.status != "active":
        raise StudySessionReferenceError("an active Owner is required")
    timestamp = _require_aware_utc(now or _utc_now())
    study_session = StudySession(
        user_id=values.user_id,
        session_type=values.session_type.value,
        status=StudySessionStatus.PLANNED.value,
        estimated_minutes=values.estimated_minutes,
        planned_task_count=values.planned_task_count,
        actual_minutes=0,
        completed_task_count=0,
        created_at=timestamp,
        updated_at=timestamp,
    )
    db.add(study_session)
    db.commit()
    db.refresh(study_session)
    return study_session


def start_study_session(
    db: Session, *, session_id: int, now: datetime | None = None
) -> StudySession:
    study_session = db.get(StudySession, session_id)
    if study_session is None:
        raise StudySessionReferenceError("study session does not exist")
    if study_session.status == StudySessionStatus.ACTIVE.value:
        return study_session
    if study_session.status != StudySessionStatus.PLANNED.value:
        raise StudySessionStateError("only a planned study session can be started")
    timestamp = _require_aware_utc(now or _utc_now())
    study_session.status = StudySessionStatus.ACTIVE.value
    study_session.started_at = timestamp
    study_session.updated_at = timestamp
    db.commit()
    db.refresh(study_session)
    return study_session


def finish_study_session(
    db: Session,
    *,
    session_id: int,
    values: StudySessionFinish,
    now: datetime | None = None,
) -> StudySession:
    study_session = db.get(StudySession, session_id)
    if study_session is None:
        raise StudySessionReferenceError("study session does not exist")
    if study_session.status != StudySessionStatus.ACTIVE.value:
        raise StudySessionStateError("only an active study session can be completed")
    if values.completed_task_count > study_session.planned_task_count:
        raise StudySessionStateError("completed tasks cannot exceed planned tasks")
    timestamp = _require_aware_utc(now or _utc_now())
    study_session.status = StudySessionStatus.COMPLETED.value
    study_session.ended_at = timestamp
    study_session.actual_minutes = values.actual_minutes
    study_session.completed_task_count = values.completed_task_count
    study_session.interruption_reason = None
    study_session.updated_at = timestamp
    db.commit()
    db.refresh(study_session)
    return study_session


def interrupt_study_session(
    db: Session,
    *,
    session_id: int,
    reason: str,
    completed_task_count: int,
    actual_minutes: int,
    now: datetime | None = None,
) -> StudySession:
    study_session = db.get(StudySession, session_id)
    if study_session is None:
        raise StudySessionReferenceError("study session does not exist")
    if study_session.status != StudySessionStatus.ACTIVE.value:
        raise StudySessionStateError("only an active study session can be interrupted")
    normalized_reason = reason.strip()
    if not normalized_reason or len(normalized_reason) > 512:
        raise StudySessionStateError("interruption reason must contain 1 to 512 characters")
    if not 0 <= completed_task_count <= study_session.planned_task_count:
        raise StudySessionStateError("completed tasks cannot exceed planned tasks")
    if not 0 <= actual_minutes <= 1440:
        raise StudySessionStateError("actual minutes must be between 0 and 1440")
    timestamp = _require_aware_utc(now or _utc_now())
    study_session.status = StudySessionStatus.INTERRUPTED.value
    study_session.ended_at = timestamp
    study_session.actual_minutes = actual_minutes
    study_session.completed_task_count = completed_task_count
    study_session.interruption_reason = normalized_reason
    study_session.updated_at = timestamp
    db.commit()
    db.refresh(study_session)
    return study_session


def _snapshot_review_state(state: CardReviewState) -> ReviewStateValues:
    return ReviewStateValues(
        due_at=state.due_at,
        stability=state.stability,
        difficulty=state.difficulty,
        elapsed_days=state.elapsed_days,
        scheduled_days=state.scheduled_days,
        reps=state.reps,
        lapses=state.lapses,
        state=state.state,
        last_rating=state.last_rating,
        last_reviewed_at=state.last_reviewed_at,
        algorithm_version=state.algorithm_version,
    )


def _validate_attempt_replay(
    existing: ReviewAttempt, values: ReviewAttemptCreate
) -> ReviewAttemptResult:
    expected = (
        values.session_id,
        values.card_id,
        values.card_revision,
        values.rating,
    )
    actual = (
        existing.session_id,
        existing.card_id,
        existing.card_revision,
        existing.rating,
    )
    if actual != expected:
        raise ReviewAttemptConflictError(
            "client_attempt_id was already used for different review context"
        )
    return ReviewAttemptResult(attempt=existing, replayed=True)


def _begin_sqlite_write_transaction(db: Session) -> None:
    deadline = monotonic() + 5
    while True:
        try:
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            return
        except OperationalError as exc:
            db.rollback()
            if "locked" not in str(exc).lower() or monotonic() >= deadline:
                raise
            sleep(0.01)


def submit_review_attempt(
    db: Session, values: ReviewAttemptCreate, *, now: datetime | None = None
) -> ReviewAttemptResult:
    if db.get_bind().dialect.name == "sqlite" and not db.in_transaction():
        # SQLite has no row-level locks. Reserve its single writer before the replay lookup so
        # concurrent submissions serialize around the unique key and state update.
        _begin_sqlite_write_transaction(db)
    existing = db.scalar(
        select(ReviewAttempt)
        .where(
            ReviewAttempt.user_id == values.user_id,
            ReviewAttempt.client_attempt_id == values.client_attempt_id,
        )
        .limit(1)
    )
    if existing is not None:
        return _validate_attempt_replay(existing, values)

    study_session = db.scalar(
        select(StudySession).where(StudySession.id == values.session_id).with_for_update()
    )
    if (
        study_session is None
        or study_session.user_id != values.user_id
        or study_session.status != StudySessionStatus.ACTIVE.value
    ):
        raise ReviewAttemptReferenceError("an active study session owned by the user is required")

    user, card = _eligible_user_and_card(db, user_id=values.user_id, card_id=values.card_id)
    del user
    if card.content_revision != values.card_revision:
        raise ReviewAttemptConflictError("card revision is stale")
    active_enrollment_id = db.scalar(
        select(CardEnrollment.id).where(
            CardEnrollment.user_id == values.user_id,
            CardEnrollment.card_id == values.card_id,
            CardEnrollment.status == EnrollmentStatus.ACTIVE.value,
        )
    )
    if active_enrollment_id is None:
        raise ReviewAttemptReferenceError("an active card enrollment is required")

    state = db.scalar(
        select(CardReviewState)
        .where(
            CardReviewState.user_id == values.user_id,
            CardReviewState.card_id == values.card_id,
        )
        .with_for_update()
    )
    if state is None:
        raise ReviewAttemptReferenceError("card review state does not exist")

    reviewed_at = _require_aware_utc(now or _utc_now())
    next_values = values.next_state.model_copy(
        update={
            "due_at": _require_aware_utc(values.next_state.due_at),
            "last_rating": values.rating,
            "last_reviewed_at": reviewed_at,
        }
    )
    before_values = _snapshot_review_state(state)
    attempt = ReviewAttempt(
        session_id=values.session_id,
        user_id=values.user_id,
        card_id=values.card_id,
        card_revision=values.card_revision,
        client_attempt_id=values.client_attempt_id,
        rating=values.rating,
        response_ms=values.response_ms,
        hint_used=values.hint_used,
        reveal_count=values.reveal_count,
        answer_payload=dict(values.answer_payload) if values.answer_payload is not None else None,
        state_before=before_values.model_dump(mode="json"),
        state_after=next_values.model_dump(mode="json"),
        due_before=before_values.due_at,
        due_after=next_values.due_at,
        algorithm_version=next_values.algorithm_version,
        reviewed_at=reviewed_at,
    )
    db.add(attempt)
    try:
        # Claim the idempotency key before changing review state.
        db.flush()
        state.due_at = next_values.due_at
        state.stability = next_values.stability
        state.difficulty = next_values.difficulty
        state.elapsed_days = next_values.elapsed_days
        state.scheduled_days = next_values.scheduled_days
        state.reps = next_values.reps
        state.lapses = next_values.lapses
        state.state = next_values.state
        state.last_rating = next_values.last_rating
        state.last_reviewed_at = next_values.last_reviewed_at
        state.algorithm_version = next_values.algorithm_version
        state.updated_at = reviewed_at
        if study_session.completed_task_count < study_session.planned_task_count:
            study_session.completed_task_count += 1
        study_session.updated_at = reviewed_at
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(
            select(ReviewAttempt)
            .where(
                ReviewAttempt.user_id == values.user_id,
                ReviewAttempt.client_attempt_id == values.client_attempt_id,
            )
            .limit(1)
        )
        if existing is None:
            raise ReviewAttemptConflictError("review attempt conflicts with existing data") from exc
        return _validate_attempt_replay(existing, values)
    db.refresh(attempt)
    return ReviewAttemptResult(attempt=attempt, replayed=False)


def create_card_issue(
    db: Session, values: CardIssueCreate, *, now: datetime | None = None
) -> CardIssue:
    user = db.get(User, values.user_id)
    card = db.get(Card, values.card_id)
    if user is None or user.status != "active" or card is None:
        raise CardIssueReferenceError("an active Owner and existing card are required")
    if card.content_revision != values.card_revision:
        raise CardIssueReferenceError("card revision is stale")
    timestamp = _require_aware_utc(now or _utc_now())
    issue = CardIssue(
        user_id=values.user_id,
        card_id=values.card_id,
        card_revision=values.card_revision,
        issue_type=values.issue_type.value,
        details=values.details,
        status="open",
        created_at=timestamp,
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)
    return issue


def resolve_card_issue(
    db: Session,
    *,
    issue_id: int,
    resolution: CardIssueResolution,
    now: datetime | None = None,
) -> CardIssue:
    issue = db.get(CardIssue, issue_id)
    if issue is None:
        raise CardIssueReferenceError("card issue does not exist")
    if issue.status in {"resolved", "dismissed"}:
        if issue.status == resolution.status.value:
            return issue
        raise CardIssueStateError("card issue already has a terminal status")
    issue.status = resolution.status.value
    issue.resolved_at = _require_aware_utc(now or _utc_now())
    db.commit()
    db.refresh(issue)
    return issue
