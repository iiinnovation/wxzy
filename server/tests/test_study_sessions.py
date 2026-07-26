from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth import require_owner
from app.catalog.models import Book, Card
from app.db import engine
from app.identity.models import User
from app.learning.fsrs_adapter import ALGORITHM_VERSION
from app.learning.models import (
    CardEnrollment,
    CardReviewState,
    DailyPlan,
    DailyPlanItem,
    ReviewAttempt,
    StudySession,
)
from app.learning.schemas import ReviewAttemptCreate
from app.learning.services import (
    ReviewAttemptConflictError,
    complete_plan_study_session,
    create_plan_study_session,
    get_next_study_task,
    interrupt_plan_study_session,
    resume_plan_study_session,
    submit_review_attempt,
)
from app.main import app

BASE_TIME = datetime(2026, 7, 25, 1, 0, tzinfo=UTC)


def _clean(db: Session) -> None:
    db.execute(delete(ReviewAttempt))
    db.execute(delete(StudySession))
    db.execute(delete(DailyPlanItem))
    db.execute(delete(DailyPlan))
    db.execute(delete(CardReviewState))
    db.execute(delete(CardEnrollment))
    db.execute(delete(User))
    db.execute(delete(Card).where(Card.external_id.like("study-session-%")))
    db.execute(delete(Book).where(Book.name.like("Study Session%")))
    db.commit()


@pytest.fixture
def db() -> Iterator[Session]:
    session = Session(engine)
    _clean(session)
    try:
        yield session
    finally:
        session.close()
        with Session(engine) as cleanup:
            _clean(cleanup)


def _seed_plan(db: Session, *, item_count: int) -> tuple[User, DailyPlan, list[Card]]:
    owner = User(status="active", timezone="Asia/Shanghai")
    book = Book(name=f"Study Session Book {item_count}", subject="测试")
    db.add_all([owner, book])
    db.flush()
    cards: list[Card] = []
    enrollments: list[CardEnrollment] = []
    for index in range(item_count):
        card = Card(
            external_id=f"study-session-{item_count}-{index}",
            book_id=book.id,
            card_type="definition",
            question=f"问题 {index}",
            answer=f"答案 {index}",
            source_excerpt="来源",
            status="published",
            content_revision=2,
            content_hash=f"{index + 1:064x}",
            answer_points=[],
            tags=[],
        )
        db.add(card)
        db.flush()
        enrollment = CardEnrollment(
            user_id=owner.id,
            card_id=card.id,
            status="active",
            priority=50,
            source="plan",
            introduced_at=BASE_TIME,
        )
        state = CardReviewState(
            user_id=owner.id,
            card_id=card.id,
            due_at=BASE_TIME,
            stability=1.0,
            difficulty=5.0,
            elapsed_days=0,
            scheduled_days=0,
            reps=0,
            lapses=0,
            state="new",
            algorithm_version=ALGORITHM_VERSION,
        )
        db.add_all([enrollment, state])
        db.flush()
        cards.append(card)
        enrollments.append(enrollment)

    plan = DailyPlan(
        user_id=owner.id,
        plan_date="2026-07-25",
        budget_minutes=20,
        estimated_minutes=item_count,
        due_count=item_count,
        new_count=0,
        weak_count=0,
        generation_version="daily-plan-v1",
        is_initial=False,
        forecast_minutes_7d=0,
        forecast_budget_7d=140,
        new_cards_paused=False,
        pause_reasons=[],
        plan_reasons=["DUE_PRIORITY"],
        generated_at=BASE_TIME,
    )
    db.add(plan)
    db.flush()
    for index, (card, enrollment) in enumerate(zip(cards, enrollments, strict=True)):
        db.add(
            DailyPlanItem(
                plan_id=plan.id,
                position=index,
                item_type="due",
                enrollment_id=enrollment.id,
                card_id=card.id,
                estimated_seconds=60,
                reason_code="DUE_TODAY",
                status="pending",
            )
        )
    db.commit()
    db.refresh(owner)
    db.refresh(plan)
    return owner, plan, cards


def _attempt(
    *, owner: User, session: StudySession, card: Card, attempt_id: str, rating: int = 3
) -> ReviewAttemptCreate:
    return ReviewAttemptCreate(
        user_id=owner.id,
        session_id=session.id,
        card_id=card.id,
        card_revision=card.content_revision,
        client_attempt_id=attempt_id,
        rating=rating,
        response_ms=1000,
        expected_state="new",
        expected_reps=0,
    )


def test_mixed_weekly_attempt_records_result_without_rescheduling_fsrs(db: Session) -> None:
    owner, plan, cards = _seed_plan(db, item_count=1)
    plan_item = plan.items[0]
    plan_item.item_type = "mixed_weekly"
    state = db.scalar(
        select(CardReviewState).where(
            CardReviewState.user_id == owner.id,
            CardReviewState.card_id == cards[0].id,
        )
    )
    assert state is not None
    before = (
        state.due_at,
        state.stability,
        state.difficulty,
        state.reps,
        state.lapses,
        state.state,
        state.last_rating,
        state.last_reviewed_at,
    )
    db.commit()
    session = create_plan_study_session(
        db,
        user_id=owner.id,
        daily_plan_id=plan.id,
        now=BASE_TIME,
    )

    result = submit_review_attempt(
        db,
        _attempt(
            owner=owner,
            session=session,
            card=cards[0],
            attempt_id="mixed-weekly-result",
            rating=1,
        ),
        now=BASE_TIME + timedelta(minutes=1),
    )
    db.refresh(state)
    db.refresh(plan_item)

    after = (
        state.due_at,
        state.stability,
        state.difficulty,
        state.reps,
        state.lapses,
        state.state,
        state.last_rating,
        state.last_reviewed_at,
    )
    assert after == before
    assert result.attempt.rating == 1
    assert result.attempt.state_after == result.attempt.state_before
    assert result.attempt.due_after == result.attempt.due_before
    assert plan_item.status == "completed"


def test_plan_cursor_interrupt_cross_day_resume_and_completed_reopen(db: Session) -> None:
    owner, plan, cards = _seed_plan(db, item_count=2)
    session = create_plan_study_session(db, user_id=owner.id, daily_plan_id=plan.id, now=BASE_TIME)
    assert session.status == "active"
    assert session.plan_date == "2026-07-25"
    assert session.planned_task_count == 2
    assert (
        get_next_study_task(db, session_id=session.id, user_id=owner.id, now=BASE_TIME).card.id
        == cards[0].id
    )

    with pytest.raises(ReviewAttemptConflictError, match="current plan task"):
        submit_review_attempt(
            db,
            _attempt(owner=owner, session=session, card=cards[1], attempt_id="wrong-order"),
            now=BASE_TIME + timedelta(minutes=1),
        )

    first_values = _attempt(owner=owner, session=session, card=cards[0], attempt_id="first")
    first = submit_review_attempt(db, first_values, now=BASE_TIME + timedelta(minutes=1))
    replay = submit_review_attempt(db, first_values, now=BASE_TIME + timedelta(minutes=2))
    db.refresh(session)
    assert first.replayed is False and replay.replayed is True
    assert session.completed_task_count == 1
    assert session.cursor_position == 1

    interrupted = interrupt_plan_study_session(
        db,
        session_id=session.id,
        user_id=owner.id,
        reason="临时离开",
        now=BASE_TIME + timedelta(minutes=2),
    )
    assert interrupted.status == "interrupted"
    assert interrupted.actual_minutes == 2
    paused_task = get_next_study_task(db, session_id=session.id, user_id=owner.id)
    assert paused_task.session.status == "interrupted"
    assert paused_task.plan_item is None

    next_day = BASE_TIME + timedelta(days=1)
    resumed = resume_plan_study_session(db, session_id=session.id, user_id=owner.id, now=next_day)
    assert resumed.plan_date == "2026-07-25"
    assert resumed.actual_minutes == 2
    assert (
        get_next_study_task(db, session_id=session.id, user_id=owner.id, now=next_day).card.id
        == cards[1].id
    )

    submit_review_attempt(
        db,
        _attempt(owner=owner, session=session, card=cards[1], attempt_id="second"),
        now=next_day + timedelta(minutes=2),
    )
    completed = complete_plan_study_session(
        db,
        session_id=session.id,
        user_id=owner.id,
        now=next_day + timedelta(minutes=3),
    )
    assert completed.status == "completed"
    assert completed.completed_task_count == 2
    assert completed.actual_minutes == 5
    assert get_next_study_task(db, session_id=session.id, user_id=owner.id).plan_item is None

    reopened = create_plan_study_session(db, user_id=owner.id, daily_plan_id=plan.id, now=next_day)
    assert reopened.id == completed.id
    assert reopened.status == "completed"


def test_empty_plan_http_session_flow(db: Session) -> None:
    owner, plan, _cards = _seed_plan(db, item_count=0)
    app.dependency_overrides[require_owner] = lambda: owner
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            started = client.post(
                "/api/v1/study-sessions",
                json={"daily_plan_id": plan.id},
            )
            assert started.status_code == 200, started.text
            body = started.json()
            assert body["status"] == "active"
            assert body["planned_task_count"] == 0

            interrupted = client.post(
                f"/api/v1/study-sessions/{body['id']}/interrupt",
                json={"reason": "稍后继续"},
            )
            assert interrupted.status_code == 200, interrupted.text
            assert interrupted.json()["status"] == "interrupted"
            blocked_next = client.get(f"/api/v1/study-sessions/{body['id']}/next")
            assert blocked_next.status_code == 200, blocked_next.text
            assert blocked_next.json()["session"]["status"] == "interrupted"
            assert blocked_next.json()["task"] is None
            resumed = client.post(f"/api/v1/study-sessions/{body['id']}/resume")
            assert resumed.status_code == 200, resumed.text
            assert resumed.json()["status"] == "active"

            next_response = client.get(f"/api/v1/study-sessions/{body['id']}/next")
            assert next_response.status_code == 200, next_response.text
            assert next_response.json()["task"] is None

            completed = client.post(f"/api/v1/study-sessions/{body['id']}/complete")
            assert completed.status_code == 200, completed.text
            assert completed.json()["status"] == "completed"

            reopened = client.post(
                "/api/v1/study-sessions",
                json={"daily_plan_id": plan.id},
            )
            assert reopened.status_code == 200, reopened.text
            assert reopened.json()["id"] == body["id"]
            assert reopened.json()["status"] == "completed"
    finally:
        app.dependency_overrides.pop(require_owner, None)


def test_nonempty_plan_http_next_attempt_and_complete(db: Session) -> None:
    owner, plan, cards = _seed_plan(db, item_count=1)
    app.dependency_overrides[require_owner] = lambda: owner
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            started = client.post(
                "/api/v1/study-sessions",
                json={"daily_plan_id": plan.id},
            )
            assert started.status_code == 200, started.text
            session = started.json()

            next_response = client.get(f"/api/v1/study-sessions/{session['id']}/next")
            assert next_response.status_code == 200, next_response.text
            task = next_response.json()["task"]
            assert task["plan_item"]["position"] == 0
            assert task["card"]["id"] == cards[0].id
            assert task["card_revision"] == 2
            assert task["review_state"]["state"] == "new"

            attempt = client.post(
                "/api/v1/review-attempts",
                json={
                    "session_id": session["id"],
                    "card_id": cards[0].id,
                    "card_revision": 2,
                    "client_attempt_id": "study-http-attempt",
                    "rating": 3,
                    "response_ms": 1200,
                    "expected_state": "new",
                    "expected_reps": 0,
                },
            )
            assert attempt.status_code == 200, attempt.text
            assert attempt.json()["replayed"] is False

            exhausted = client.get(f"/api/v1/study-sessions/{session['id']}/next")
            assert exhausted.status_code == 200, exhausted.text
            assert exhausted.json()["task"] is None
            assert exhausted.json()["session"]["completed_task_count"] == 1
            assert exhausted.json()["session"]["cursor_position"] == 1

            completed = client.post(f"/api/v1/study-sessions/{session['id']}/complete")
            assert completed.status_code == 200, completed.text
            assert completed.json()["status"] == "completed"
    finally:
        app.dependency_overrides.pop(require_owner, None)
