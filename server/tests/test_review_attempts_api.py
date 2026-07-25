from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.v1.identity import get_wechat_client
from app.catalog.models import Book, Card
from app.config import AppEnvironment, AuthMode, Settings
from app.db import engine
from app.identity.models import LearningProfile, LearningProfileAudit, User, UserSession
from app.identity.wechat import WeChatCodeError, WeChatIdentity
from app.learning.fsrs_adapter import ALGORITHM_VERSION, schedule
from app.learning.models import (
    CardEnrollment,
    CardReviewState,
    ReviewAttempt,
    StudySession,
)
from app.learning.schemas import EnrollmentCreate
from app.learning.services import enroll_card, introduce_enrollment
from app.main import app

BASE_TIME = datetime(2026, 7, 22, 4, 0, tzinfo=UTC)


def _clean(db: Session) -> None:
    db.execute(delete(ReviewAttempt))
    db.execute(delete(StudySession))
    db.execute(delete(CardReviewState))
    db.execute(delete(CardEnrollment))
    db.execute(delete(LearningProfileAudit))
    db.execute(delete(LearningProfile))
    db.execute(delete(UserSession))
    db.execute(delete(User))
    db.execute(delete(Card).where(Card.external_id.like("review-api-%")))
    db.execute(delete(Book).where(Book.name.like("Review API%")))
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


class FakeWeChatClient:
    def exchange(self, code: str) -> WeChatIdentity:
        if code != "valid-code":
            raise WeChatCodeError()
        return WeChatIdentity(openid="openid-review-api")


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
    return {"Authorization": f"Bearer {token}", "X-Request-ID": "req_review"}


def _seed_card(db: Session, *, owner_id: int) -> int:
    book = Book(name=f"Review API Book {owner_id}", subject="测试")
    db.add(book)
    db.flush()
    card = Card(
        external_id=f"review-api-{owner_id}",
        book_id=book.id,
        card_type="definition",
        question="问题",
        answer="答案",
        source_excerpt="来源摘录",
        status="published",
        content_revision=2,
        content_hash="b" * 64,
        answer_points=[],
        tags=[],
    )
    db.add(card)
    db.commit()
    enrollment = enroll_card(
        db,
        EnrollmentCreate(user_id=owner_id, card_id=card.id),
        now=BASE_TIME,
    ).enrollment
    introduce_enrollment(db, enrollment_id=enrollment.id, now=BASE_TIME)
    return card.id


def test_study_session_and_review_attempt_http_flow(
    db: Session, auth_context: tuple[TestClient, Settings]
) -> None:
    client, _settings = auth_context
    login = _login(client)
    token = login["access_token"]
    owner_id = login["owner"]["id"]
    card_id = _seed_card(db, owner_id=owner_id)

    session_response = client.post(
        "/api/v1/study-sessions",
        headers=_headers(token),
        json={
            "session_type": "daily",
            "estimated_minutes": 15,
            "planned_task_count": 3,
            "auto_start": True,
        },
    )
    assert session_response.status_code == 200, session_response.text
    session_body = session_response.json()
    assert session_body["status"] == "active"
    assert session_body["user_id"] == owner_id
    assert session_body["planned_task_count"] == 3
    assert session_body["started_at"] is not None
    session_id = session_body["id"]

    payload = {
        "session_id": session_id,
        "card_id": card_id,
        "card_revision": 2,
        "client_attempt_id": "http-device-attempt-001",
        "rating": 3,
        "response_ms": 3500,
        "hint_used": False,
        "reveal_count": 0,
        "answer_payload": {"text": "http answer"},
        "expected_state": "new",
        "expected_reps": 0,
    }
    first = client.post(
        "/api/v1/review-attempts",
        headers=_headers(token),
        json=payload,
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["replayed"] is False
    assert first_body["client_attempt_id"] == "http-device-attempt-001"
    assert first_body["algorithm_version"] == ALGORITHM_VERSION
    assert first_body["state_before"]["state"] == "new"
    assert first_body["state_after"]["last_rating"] == 3

    reviewed_at = datetime.fromisoformat(first_body["reviewed_at"].replace("Z", "+00:00"))
    expected = schedule(
        rating=3,
        now=reviewed_at,
        stability=1.0,
        difficulty=5.0,
        reps=0,
        lapses=0,
        state="new",
        last_reviewed_at=None,
        due_at=BASE_TIME,
    )
    assert datetime.fromisoformat(first_body["due_after"].replace("Z", "+00:00")) == expected.due_at
    assert first_body["state_after"]["state"] == expected.state

    retry = client.post(
        "/api/v1/review-attempts",
        headers=_headers(token),
        json={**payload, "response_ms": 9999, "answer_payload": {"text": "retry payload"}},
    )
    assert retry.status_code == 200, retry.text
    retry_body = retry.json()
    assert retry_body["replayed"] is True
    assert retry_body["id"] == first_body["id"]
    assert retry_body["response_ms"] == 3500
    assert db.scalar(select(func.count()).select_from(ReviewAttempt)) == 1

    conflict = client.post(
        "/api/v1/review-attempts",
        headers=_headers(token),
        json={**payload, "rating": 2, "client_attempt_id": "http-device-attempt-001"},
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["code"] == "REVIEW_ATTEMPT_CONFLICT"

    stale = client.post(
        "/api/v1/review-attempts",
        headers=_headers(token),
        json={
            **payload,
            "client_attempt_id": "http-device-attempt-002",
            "expected_state": "review",
            "expected_reps": 9,
        },
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["code"] == "REVIEW_ATTEMPT_CONFLICT"


def test_study_session_without_auto_start_stays_planned(
    db: Session, auth_context: tuple[TestClient, Settings]
) -> None:
    client, _settings = auth_context
    token = _login(client)["access_token"]
    response = client.post(
        "/api/v1/study-sessions",
        headers=_headers(token),
        json={"planned_task_count": 1, "auto_start": False},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "planned"
    assert body["started_at"] is None
    assert db.get(StudySession, body["id"]) is not None
