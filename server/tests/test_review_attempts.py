from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from app.catalog.models import Book, Card
from app.db import engine
from app.identity.models import LearningProfile, User, UserSession
from app.identity.schemas import OwnerCreate
from app.identity.services import create_owner_with_default_profile
from app.learning.models import (
    CardEnrollment,
    CardIssue,
    CardReviewState,
    ReviewAttempt,
    StudySession,
)
from app.learning.schemas import (
    CardIssueCreate,
    CardIssueResolution,
    CardIssueStatus,
    CardIssueType,
    EnrollmentCreate,
    ReviewAttemptCreate,
    ReviewStateValues,
    StudySessionCreate,
    StudySessionFinish,
)
from app.learning.services import (
    CardIssueStateError,
    ReviewAttemptConflictError,
    StudySessionStateError,
    create_card_issue,
    create_study_session,
    enroll_card,
    finish_study_session,
    interrupt_study_session,
    introduce_enrollment,
    resolve_card_issue,
    start_study_session,
    submit_review_attempt,
)

BASE_TIME = datetime(2026, 7, 22, 4, 0, tzinfo=UTC)


def _clean_rows(db: Session) -> None:
    db.execute(delete(ReviewAttempt))
    db.execute(delete(CardIssue))
    db.execute(delete(StudySession))
    db.execute(delete(CardReviewState))
    db.execute(delete(CardEnrollment))
    db.execute(delete(LearningProfile))
    db.execute(delete(UserSession))
    db.execute(delete(User))
    db.execute(delete(Card).where(Card.external_id.like("attempt-test-%")))
    db.execute(delete(Book).where(Book.name.like("Attempt Test%")))
    db.commit()


@pytest.fixture
def db() -> Iterator[Session]:
    with Session(engine) as session:
        _clean_rows(session)
        yield session
        session.rollback()
        _clean_rows(session)


def _create_context(db: Session, *, planned_tasks: int = 3) -> tuple[int, int, int]:
    owner = create_owner_with_default_profile(
        db,
        OwnerCreate(display_name="Attempt Test Owner", timezone="Asia/Shanghai"),
        now=BASE_TIME,
    )
    book = Book(name=f"Attempt Test Book {owner.id}", subject="测试")
    db.add(book)
    db.flush()
    card = Card(
        external_id=f"attempt-test-{owner.id}",
        book_id=book.id,
        card_type="definition",
        question="问题",
        answer="答案",
        source_excerpt="来源摘录",
        status="published",
        content_revision=2,
        content_hash="a" * 64,
        answer_points=[],
        tags=[],
    )
    db.add(card)
    db.commit()
    owner_id = owner.id
    card_id = card.id
    enrollment = enroll_card(
        db,
        EnrollmentCreate(user_id=owner_id, card_id=card_id),
        now=BASE_TIME,
    ).enrollment
    introduce_enrollment(db, enrollment_id=enrollment.id, now=BASE_TIME)
    study_session = create_study_session(
        db,
        StudySessionCreate(
            user_id=owner_id,
            estimated_minutes=10,
            planned_task_count=planned_tasks,
        ),
        now=BASE_TIME,
    )
    start_study_session(db, session_id=study_session.id, now=BASE_TIME)
    return owner_id, card_id, study_session.id


def _attempt_values(
    *,
    user_id: int,
    card_id: int,
    session_id: int,
    client_attempt_id: str = "device-attempt-001",
    rating: int = 3,
) -> ReviewAttemptCreate:
    return ReviewAttemptCreate(
        user_id=user_id,
        session_id=session_id,
        card_id=card_id,
        card_revision=2,
        client_attempt_id=client_attempt_id,
        rating=rating,
        response_ms=4200,
        hint_used=True,
        reveal_count=1,
        answer_payload={"text": "测试作答", "confidence": 4},
        next_state=ReviewStateValues(
            due_at=BASE_TIME + timedelta(days=2),
            stability=2.5,
            difficulty=4.7,
            elapsed_days=0,
            scheduled_days=2,
            reps=1,
            lapses=0,
            state="review",
            algorithm_version="fsrs-v1",
        ),
    )


def test_submit_review_attempt_updates_state_and_preserves_audit_snapshot(db: Session) -> None:
    user_id, card_id, session_id = _create_context(db)
    values = _attempt_values(user_id=user_id, card_id=card_id, session_id=session_id)

    result = submit_review_attempt(db, values, now=BASE_TIME + timedelta(minutes=2))

    assert result.replayed is False
    assert result.attempt.card_revision == 2
    assert result.attempt.due_before == BASE_TIME
    assert result.attempt.due_after == BASE_TIME + timedelta(days=2)
    assert result.attempt.state_before["state"] == "new"
    assert result.attempt.state_before["reps"] == 0
    assert result.attempt.state_after["state"] == "review"
    assert result.attempt.state_after["last_rating"] == 3
    assert result.attempt.answer_payload == {"text": "测试作答", "confidence": 4}

    state = db.scalar(
        select(CardReviewState).where(
            CardReviewState.user_id == user_id, CardReviewState.card_id == card_id
        )
    )
    study_session = db.get(StudySession, session_id)
    assert state is not None and state.reps == 1 and state.due_at == result.attempt.due_after
    assert state.last_rating == 3 and state.last_reviewed_at == BASE_TIME + timedelta(minutes=2)
    assert study_session is not None and study_session.completed_task_count == 1


def test_duplicate_attempt_returns_first_result_without_second_state_update(db: Session) -> None:
    user_id, card_id, session_id = _create_context(db)
    values = _attempt_values(user_id=user_id, card_id=card_id, session_id=session_id)
    first = submit_review_attempt(db, values, now=BASE_TIME + timedelta(minutes=2))
    retried_values = values.model_copy(
        update={"response_ms": 9999, "answer_payload": {"text": "网络重试中的不同载荷"}}
    )

    replay = submit_review_attempt(db, retried_values, now=BASE_TIME + timedelta(minutes=3))

    assert replay.replayed is True
    assert replay.attempt.id == first.attempt.id
    assert replay.attempt.response_ms == 4200
    assert db.scalar(select(func.count()).select_from(ReviewAttempt)) == 1
    state = db.scalar(select(CardReviewState).where(CardReviewState.card_id == card_id))
    assert state is not None and state.reps == 1


def test_duplicate_attempt_with_different_context_is_a_conflict(db: Session) -> None:
    user_id, card_id, session_id = _create_context(db)
    values = _attempt_values(user_id=user_id, card_id=card_id, session_id=session_id)
    submit_review_attempt(db, values, now=BASE_TIME + timedelta(minutes=2))

    conflicting = _attempt_values(
        user_id=user_id,
        card_id=card_id,
        session_id=session_id,
        rating=2,
    )
    with pytest.raises(ReviewAttemptConflictError, match="different review context"):
        submit_review_attempt(db, conflicting, now=BASE_TIME + timedelta(minutes=3))


def test_concurrent_duplicate_submission_creates_one_attempt(db: Session) -> None:
    user_id, card_id, session_id = _create_context(db)
    values = _attempt_values(user_id=user_id, card_id=card_id, session_id=session_id)

    def submit() -> tuple[int, bool]:
        with Session(engine) as thread_db:
            result = submit_review_attempt(thread_db, values, now=BASE_TIME + timedelta(minutes=2))
            return result.attempt.id, result.replayed

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: submit(), range(2)))

    assert len({attempt_id for attempt_id, _replayed in results}) == 1
    assert sorted(replayed for _attempt_id, replayed in results) == [False, True]
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(ReviewAttempt)) == 1
    state = db.scalar(select(CardReviewState).where(CardReviewState.card_id == card_id))
    assert state is not None and state.reps == 1


@pytest.mark.postgres
def test_postgres_concurrent_duplicate_submission_creates_one_attempt() -> None:
    url = os.environ.get("WXZY_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("set WXZY_TEST_POSTGRES_URL to run the PostgreSQL concurrency check")
    postgres_engine = create_engine(url, pool_pre_ping=True)
    try:
        with Session(postgres_engine) as setup_db:
            _clean_rows(setup_db)
            user_id, card_id, session_id = _create_context(setup_db)
        values = _attempt_values(user_id=user_id, card_id=card_id, session_id=session_id)

        def submit() -> tuple[int, bool]:
            with Session(postgres_engine) as thread_db:
                result = submit_review_attempt(
                    thread_db, values, now=BASE_TIME + timedelta(minutes=2)
                )
                return result.attempt.id, result.replayed

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _index: submit(), range(2)))

        assert len({attempt_id for attempt_id, _replayed in results}) == 1
        assert sorted(replayed for _attempt_id, replayed in results) == [False, True]
        with Session(postgres_engine) as verify_db:
            assert verify_db.scalar(select(func.count()).select_from(ReviewAttempt)) == 1
            state = verify_db.scalar(
                select(CardReviewState).where(CardReviewState.card_id == card_id)
            )
            assert state is not None and state.reps == 1
            _clean_rows(verify_db)
    finally:
        postgres_engine.dispose()


def test_study_session_complete_and_interrupt_lifecycle(db: Session) -> None:
    user_id, _card_id, active_session_id = _create_context(db, planned_tasks=3)
    completed = finish_study_session(
        db,
        session_id=active_session_id,
        values=StudySessionFinish(completed_task_count=2, actual_minutes=8),
        now=BASE_TIME + timedelta(minutes=8),
    )
    assert completed.status == "completed"
    assert completed.ended_at == BASE_TIME + timedelta(minutes=8)
    assert completed.completed_task_count == 2
    with pytest.raises(StudySessionStateError, match="active"):
        finish_study_session(
            db,
            session_id=active_session_id,
            values=StudySessionFinish(completed_task_count=2, actual_minutes=8),
        )

    interrupted_session = create_study_session(
        db,
        StudySessionCreate(user_id=user_id, planned_task_count=5),
        now=BASE_TIME,
    )
    start_study_session(db, session_id=interrupted_session.id, now=BASE_TIME)
    interrupted = interrupt_study_session(
        db,
        session_id=interrupted_session.id,
        reason="临时离开",
        completed_task_count=1,
        actual_minutes=3,
        now=BASE_TIME + timedelta(minutes=3),
    )
    assert interrupted.status == "interrupted"
    assert interrupted.interruption_reason == "临时离开"


def test_card_issue_categories_and_terminal_resolution(db: Session) -> None:
    user_id, card_id, _session_id = _create_context(db)
    issues = [
        create_card_issue(
            db,
            CardIssueCreate(
                user_id=user_id,
                card_id=card_id,
                card_revision=2,
                issue_type=issue_type,
                details="需要核对",
            ),
            now=BASE_TIME,
        )
        for issue_type in CardIssueType
    ]
    assert {issue.issue_type for issue in issues} == {item.value for item in CardIssueType}
    assert {issue.status for issue in issues} == {"open"}

    resolution = CardIssueResolution(status=CardIssueStatus.RESOLVED)
    resolved = resolve_card_issue(db, issue_id=issues[0].id, resolution=resolution, now=BASE_TIME)
    replay = resolve_card_issue(db, issue_id=issues[0].id, resolution=resolution, now=BASE_TIME)
    assert resolved.status == "resolved" and replay.id == resolved.id
    with pytest.raises(CardIssueStateError, match="terminal"):
        resolve_card_issue(
            db,
            issue_id=issues[0].id,
            resolution=CardIssueResolution(status=CardIssueStatus.DISMISSED),
            now=BASE_TIME,
        )


def test_answer_payload_is_bounded() -> None:
    with pytest.raises(ValidationError, match="4000"):
        ReviewAttemptCreate.model_validate(
            {
                **_attempt_values(user_id=1, card_id=1, session_id=1).model_dump(),
                "answer_payload": {"text": "x" * 4001},
            }
        )
