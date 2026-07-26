from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.v1.identity import get_wechat_client
from app.catalog.models import Book, Card
from app.config import AppEnvironment, AuthMode, Settings
from app.db import engine
from app.identity.models import LearningProfile, LearningProfileAudit, User, UserSession
from app.identity.schemas import OwnerCreate
from app.identity.services import create_owner_with_default_profile
from app.identity.wechat import WeChatCodeError, WeChatIdentity
from app.learning.daily_plan import (
    GENERATION_VERSION,
    adjust_today_budget,
    generate_daily_plan,
    get_or_create_today_plan,
)
from app.learning.models import (
    CardEnrollment,
    CardIssue,
    CardReviewState,
    DailyPlan,
    DailyPlanItem,
    ReviewAttempt,
    StudySession,
)
from app.learning.schemas import EnrollmentCreate
from app.learning.services import create_plan_study_session, enroll_card, introduce_enrollment
from app.main import app

BASE_TIME = datetime(2026, 7, 25, 2, 0, tzinfo=UTC)  # Asia/Shanghai 10:00 on Saturday


def _clean(db: Session) -> None:
    db.execute(delete(DailyPlanItem))
    db.execute(delete(DailyPlan))
    db.execute(delete(ReviewAttempt))
    db.execute(delete(CardIssue))
    db.execute(delete(StudySession))
    db.execute(delete(CardReviewState))
    db.execute(delete(CardEnrollment))
    db.execute(delete(LearningProfileAudit))
    db.execute(delete(LearningProfile))
    db.execute(delete(UserSession))
    db.execute(delete(User))
    db.execute(delete(Card).where(Card.external_id.like("daily-plan-%")))
    db.execute(delete(Book).where(Book.name.like("Daily Plan%")))
    db.commit()


@pytest.fixture
def db() -> Iterator[Session]:
    session = Session(engine)
    _clean(session)
    try:
        yield session
    finally:
        try:
            session.rollback()
        except Exception:
            pass
        try:
            session.close()
        except Exception:
            pass
        with Session(engine) as cleanup:
            _clean(cleanup)


def _owner(db: Session, *, daily_minutes: int = 20, new_card_ceiling: int = 5) -> User:
    owner = create_owner_with_default_profile(
        db,
        OwnerCreate(display_name="Daily Plan Owner", timezone="Asia/Shanghai"),
        now=BASE_TIME,
    )
    profile = db.scalar(select(LearningProfile).where(LearningProfile.user_id == owner.id))
    assert profile is not None
    profile.daily_minutes = daily_minutes
    profile.new_card_ceiling = new_card_ceiling
    profile.subject_priorities = {"方剂学": 5, "中药学": 3}
    db.commit()
    db.refresh(owner)
    return owner


def _book_card(
    db: Session,
    *,
    suffix: str,
    subject: str = "方剂学",
    question: str | None = None,
) -> Card:
    book = Book(name=f"Daily Plan {subject} {suffix}", subject=subject)
    db.add(book)
    db.flush()
    card = Card(
        external_id=f"daily-plan-{suffix}",
        book_id=book.id,
        card_type="definition",
        question=question or f"Q-{suffix}",
        answer=f"A-{suffix}",
        source_excerpt="excerpt",
        status="published",
        content_revision=1,
        content_hash=(f"{abs(hash(suffix)):064x}")[-64:],
        answer_points=[],
        tags=[],
    )
    db.add(card)
    db.commit()
    db.refresh(card)
    return card


def _activate(
    db: Session,
    *,
    user_id: int,
    card_id: int,
    due_at: datetime,
    state: str = "review",
    lapses: int = 0,
    reps: int = 3,
    last_rating: int | None = 3,
) -> CardEnrollment:
    enrollment = enroll_card(
        db,
        EnrollmentCreate(user_id=user_id, card_id=card_id, priority=50),
        now=BASE_TIME,
    ).enrollment
    introduce_enrollment(db, enrollment_id=enrollment.id, now=BASE_TIME)
    review_state = db.scalar(
        select(CardReviewState).where(
            CardReviewState.user_id == user_id,
            CardReviewState.card_id == card_id,
        )
    )
    assert review_state is not None
    review_state.due_at = due_at
    review_state.state = state
    review_state.lapses = lapses
    review_state.reps = reps
    review_state.last_rating = last_rating
    review_state.last_reviewed_at = BASE_TIME - timedelta(days=1)
    db.commit()
    db.refresh(enrollment)
    return enrollment


def _queue(db: Session, *, user_id: int, card_id: int, priority: int = 50) -> CardEnrollment:
    return enroll_card(
        db,
        EnrollmentCreate(user_id=user_id, card_id=card_id, priority=priority),
        now=BASE_TIME,
    ).enrollment


def test_cold_start_marks_initial_and_due_first(db: Session) -> None:
    owner = _owner(db, daily_minutes=20)
    due_card = _book_card(db, suffix="due1")
    new_card = _book_card(db, suffix="new1", subject="中药学")
    _activate(db, user_id=owner.id, card_id=due_card.id, due_at=BASE_TIME - timedelta(hours=2))
    _queue(db, user_id=owner.id, card_id=new_card.id, priority=80)

    plan = generate_daily_plan(db, user_id=owner.id, now=BASE_TIME)

    assert plan.generation_version == GENERATION_VERSION
    assert plan.is_initial is True
    assert plan.plan_date == "2026-07-25"
    assert plan.budget_minutes == 20
    assert plan.due_count >= 1
    assert any(item.reason_code in {"DUE", "OVERDUE"} for item in plan.items)
    # With room after one due (~45s), new cards may enter.
    assert "INITIAL_CONSERVATIVE_DEFAULTS" in plan.plan_reasons
    assert all(item.reason_code for item in plan.items)


def test_backlog_pauses_new_cards(db: Session) -> None:
    owner = _owner(db, daily_minutes=10, new_card_ceiling=10)
    # 20 due cards * 45s = 900s = 15 min > 10 min budget
    for index in range(20):
        card = _book_card(db, suffix=f"backlog{index:02d}")
        _activate(
            db,
            user_id=owner.id,
            card_id=card.id,
            due_at=BASE_TIME - timedelta(hours=index + 1),
        )
    new_card = _book_card(db, suffix="new-backlog", subject="中药学")
    _queue(db, user_id=owner.id, card_id=new_card.id, priority=99)

    plan = generate_daily_plan(db, user_id=owner.id, now=BASE_TIME)

    assert plan.new_count == 0
    assert plan.new_cards_paused is True
    assert "BACKLOG_EXCEEDS_BUDGET" in plan.pause_reasons
    assert all(item.item_type in {"due", "overdue"} for item in plan.items)
    assert plan.due_count == len(plan.items)
    assert plan.due_count > 0


def test_forecast_over_budget_pauses_new_cards(db: Session) -> None:
    # 100 future-due cards * 45s ~= 75 min; 7 * 10 min budget = 70 => pause new.
    owner = _owner(db, daily_minutes=10, new_card_ceiling=5)
    for index in range(100):
        card = _book_card(db, suffix=f"forecast{index:03d}")
        due_at = BASE_TIME + timedelta(days=2, minutes=index)
        if index < 1:
            due_at = BASE_TIME - timedelta(minutes=5)
        _activate(db, user_id=owner.id, card_id=card.id, due_at=due_at)
    new_card = _book_card(db, suffix="forecast-new")
    _queue(db, user_id=owner.id, card_id=new_card.id, priority=90)

    plan = generate_daily_plan(db, user_id=owner.id, now=BASE_TIME)

    assert plan.forecast_minutes_7d > plan.forecast_budget_7d
    assert plan.new_cards_paused is True
    assert "FORECAST_7D_OVER_BUDGET" in plan.pause_reasons
    assert plan.new_count == 0


def test_same_inputs_produce_stable_plan(db: Session) -> None:
    owner = _owner(db, daily_minutes=25)
    cards = []
    for index in range(6):
        card = _book_card(db, suffix=f"stable{index}")
        cards.append(card)
        _activate(
            db,
            user_id=owner.id,
            card_id=card.id,
            due_at=BASE_TIME - timedelta(hours=index + 1),
        )
    for index in range(3):
        card = _book_card(db, suffix=f"stable-new{index}", subject="中药学")
        _queue(db, user_id=owner.id, card_id=card.id, priority=60 - index)

    first = generate_daily_plan(db, user_id=owner.id, now=BASE_TIME)
    first_snapshot = [
        (item.position, item.card_id, item.reason_code, item.item_type)
        for item in sorted(first.items, key=lambda row: row.position)
    ]
    # regenerate same day
    second = generate_daily_plan(db, user_id=owner.id, now=BASE_TIME, existing=first)
    second_snapshot = [
        (item.position, item.card_id, item.reason_code, item.item_type)
        for item in sorted(second.items, key=lambda row: row.position)
    ]
    assert first_snapshot == second_snapshot
    assert first.estimated_minutes == second.estimated_minutes
    assert first.pause_reasons == second.pause_reasons


def test_budget_reduction_keeps_pending_items(db: Session) -> None:
    owner = _owner(db, daily_minutes=30)
    for index in range(8):
        card = _book_card(db, suffix=f"keep{index}")
        _activate(
            db,
            user_id=owner.id,
            card_id=card.id,
            due_at=BASE_TIME - timedelta(minutes=30 * (index + 1)),
        )

    plan = generate_daily_plan(db, user_id=owner.id, now=BASE_TIME)
    pending_card_ids = {item.card_id for item in plan.items if item.status == "pending"}
    assert len(pending_card_ids) >= 2

    reduced = adjust_today_budget(db, user_id=owner.id, budget_minutes=5, now=BASE_TIME)
    reduced_ids = {item.card_id for item in reduced.items if item.status == "pending"}
    assert pending_card_ids.issubset(reduced_ids)
    assert reduced.adjusted_budget_minutes == 5
    assert "BUDGET_REDUCED_KEEP_PENDING" in reduced.plan_reasons or reduced.estimated_minutes >= 5


def test_budget_increase_is_explainable(db: Session) -> None:
    owner = _owner(db, daily_minutes=10, new_card_ceiling=5)
    due_card = _book_card(db, suffix="inc-due")
    _activate(db, user_id=owner.id, card_id=due_card.id, due_at=BASE_TIME - timedelta(hours=1))
    for index in range(5):
        card = _book_card(db, suffix=f"inc-new{index}", subject="中药学")
        _queue(db, user_id=owner.id, card_id=card.id, priority=70)

    small = generate_daily_plan(db, user_id=owner.id, now=BASE_TIME)
    larger = adjust_today_budget(db, user_id=owner.id, budget_minutes=60, now=BASE_TIME)
    assert larger.adjusted_budget_minutes == 60
    # More or equal items after budget increase when not paused by forecast alone.
    assert len(larger.items) >= len(small.items)
    assert larger.budget_minutes == 10


def test_budget_increase_synchronizes_existing_plan_session_total(db: Session) -> None:
    owner = _owner(db, daily_minutes=5, new_card_ceiling=20)
    due_card = _book_card(db, suffix="session-sync-due")
    _activate(db, user_id=owner.id, card_id=due_card.id, due_at=BASE_TIME - timedelta(hours=1))
    for index in range(10):
        card = _book_card(db, suffix=f"session-sync-new{index}", subject="中药学")
        _queue(db, user_id=owner.id, card_id=card.id, priority=70)

    small = generate_daily_plan(db, user_id=owner.id, now=BASE_TIME)
    study_session = create_plan_study_session(
        db,
        user_id=owner.id,
        daily_plan_id=small.id,
        now=BASE_TIME,
    )
    original_total = study_session.planned_task_count
    first_item = min(small.items, key=lambda item: item.position)
    first_item_id = first_item.id
    first_card_id = first_item.card_id
    first_item.status = "completed"
    study_session.completed_task_count = 1
    study_session.cursor_position = 1
    db.commit()

    larger = adjust_today_budget(db, user_id=owner.id, budget_minutes=60, now=BASE_TIME)
    db.refresh(study_session)

    assert len(larger.items) > original_total
    assert db.get(DailyPlanItem, first_item_id).status == "completed"
    assert sum(item.card_id == first_card_id for item in larger.items) == 1
    pending_count = sum(item.status == "pending" for item in larger.items)
    assert study_session.planned_task_count == study_session.completed_task_count + pending_count
    assert study_session.estimated_minutes == larger.estimated_minutes


def test_weak_and_repair_reason_codes(db: Session) -> None:
    owner = _owner(db, daily_minutes=40)
    # One due so plan is non-empty path, remaining budget for weak/repair.
    due_card = _book_card(db, suffix="weak-due")
    _activate(db, user_id=owner.id, card_id=due_card.id, due_at=BASE_TIME - timedelta(minutes=10))

    weak_card = _book_card(db, suffix="weak-card")
    _activate(
        db,
        user_id=owner.id,
        card_id=weak_card.id,
        due_at=BASE_TIME + timedelta(days=3),
        lapses=3,
        reps=5,
        last_rating=1,
    )

    repair_card = _book_card(db, suffix="repair-card")
    _activate(
        db,
        user_id=owner.id,
        card_id=repair_card.id,
        due_at=BASE_TIME + timedelta(days=2),
    )
    db.add(
        CardIssue(
            user_id=owner.id,
            card_id=repair_card.id,
            card_revision=1,
            issue_type="concept_confusion",
            details="易混淆",
            status="open",
            created_at=BASE_TIME,
        )
    )
    db.commit()

    plan = generate_daily_plan(db, user_id=owner.id, now=BASE_TIME)
    codes = {item.reason_code for item in plan.items}
    assert "DUE" in codes or "OVERDUE" in codes
    assert "REPAIR_CARD_ISSUE" in codes
    repair_item = next(item for item in plan.items if item.reason_code == "REPAIR_CARD_ISSUE")
    assert "compare_cards" in (repair_item.reason_detail or "")
    assert plan.weak_count >= 1


def test_get_or_create_is_idempotent(db: Session) -> None:
    owner = _owner(db)
    card = _book_card(db, suffix="idem")
    _activate(db, user_id=owner.id, card_id=card.id, due_at=BASE_TIME - timedelta(hours=1))

    first = get_or_create_today_plan(db, user_id=owner.id, now=BASE_TIME)
    second = get_or_create_today_plan(db, user_id=owner.id, now=BASE_TIME)
    assert first.id == second.id
    assert len(first.items) == len(second.items)


class FakeWeChatClient:
    def exchange(self, code: str) -> WeChatIdentity:
        if code != "valid-code":
            raise WeChatCodeError()
        return WeChatIdentity(openid="openid-daily-plan")


@pytest.fixture
def auth_context(db: Session) -> Iterator[tuple[TestClient, Settings]]:
    del db
    settings = Settings(
        environment=AppEnvironment.TEST,
        auth_mode=AuthMode.WECHAT,
        wechat_app_id="wx-test-app",
        wechat_app_secret="wechat-test-secret",
        session_ttl_seconds=3600,
    )
    app.dependency_overrides[get_wechat_client] = lambda: FakeWeChatClient()
    from app.config import get_settings

    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, settings
    app.dependency_overrides.pop(get_wechat_client, None)
    app.dependency_overrides.pop(get_settings, None)


def _login(client: TestClient) -> dict[str, Any]:
    response = client.post("/api/v1/auth/wechat", json={"code": "valid-code"})
    assert response.status_code == 200, response.text
    return response.json()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Request-ID": "req_daily_plan"}


def test_learning_today_api(db: Session, auth_context: tuple[TestClient, Settings]) -> None:
    client, _settings = auth_context
    payload = _login(client)
    token = payload["access_token"]
    owner_id = int(payload["owner"]["id"])

    profile = db.scalar(select(LearningProfile).where(LearningProfile.user_id == owner_id))
    assert profile is not None
    profile.daily_minutes = 20
    profile.new_card_ceiling = 5
    db.commit()

    card = _book_card(db, suffix="api-due")
    # API path uses server now; keep due firmly in the past relative to wall clock.
    _activate(
        db,
        user_id=owner_id,
        card_id=card.id,
        due_at=datetime.now(UTC) - timedelta(hours=2),
    )

    response = client.get("/api/v1/learning/today", headers=_headers(token))
    assert response.status_code == 200, response.text
    body = response.json()
    # Owner timezone Asia/Shanghai; wall clock may vary, so accept today's local date.
    assert body["due_count"] >= 1
    assert body["generation_version"] == GENERATION_VERSION
    assert isinstance(body["items"], list)
    assert body["effective_budget_minutes"] == 20
    assert body["budget_minutes"] == 20

    patched = client.patch(
        "/api/v1/learning/today",
        headers=_headers(token),
        json={"budget_minutes": 40},
    )
    assert patched.status_code == 200, patched.text
    patched_body = patched.json()
    assert patched_body["adjusted_budget_minutes"] == 40
    assert patched_body["effective_budget_minutes"] == 40
    assert patched_body["budget_minutes"] == 20
