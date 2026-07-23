from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.v1.identity import get_wechat_client
from app.config import AppEnvironment, AuthMode, Settings
from app.db import engine
from app.identity.models import LearningProfile, LearningProfileAudit, User, UserSession
from app.identity.schemas import LearningProfileUpdate, OwnerCreate
from app.identity.services import create_owner_with_default_profile
from app.identity.wechat import WeChatCodeError, WeChatIdentity
from app.learning.models import (
    CardEnrollment,
    CardIssue,
    CardReviewState,
    ReviewAttempt,
    StudySession,
)
from app.main import app


def _clean_identity_rows(db: Session) -> None:
    db.execute(delete(ReviewAttempt))
    db.execute(delete(CardIssue))
    db.execute(delete(StudySession))
    db.execute(delete(CardReviewState))
    db.execute(delete(CardEnrollment))
    db.execute(delete(LearningProfileAudit))
    db.execute(delete(LearningProfile))
    db.execute(delete(UserSession))
    db.execute(delete(User))
    db.commit()


@pytest.fixture
def db() -> Iterator[Session]:
    session = Session(engine)
    _clean_identity_rows(session)
    try:
        yield session
    finally:
        session.close()
        with Session(engine) as cleanup:
            _clean_identity_rows(cleanup)


class FakeWeChatClient:
    def exchange(self, code: str) -> WeChatIdentity:
        if code != "valid-code":
            raise WeChatCodeError()
        return WeChatIdentity(openid="openid-profile")


@pytest.fixture
def auth_context(db: Session) -> Iterator[tuple[TestClient, Settings]]:
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


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Request-ID": "req_profile"}


def test_get_default_learning_profile(
    db: Session, auth_context: tuple[TestClient, Settings]
) -> None:
    client, _settings = auth_context
    payload = _login(client)
    token = payload["access_token"]

    response = client.get("/api/v1/me/learning-profile", headers=_auth_headers(token))

    assert response.status_code == 200
    body = response.json()
    assert body["goal_type"] == "daily_learning"
    assert body["daily_minutes"] == 20
    assert body["study_days"] == [True] * 7
    assert body["desired_retention"] == pytest.approx(0.90)
    assert body["new_card_ceiling"] == 5
    assert body["subject_priorities"] == {}
    assert body["initial_self_assessment"] == {}
    assert body["onboarding_completed_at"] is None
    assert body["display_name"] is None
    assert body["timezone"] == "Asia/Shanghai"
    assert body["updated_at"].endswith("+00:00") or body["updated_at"].endswith("Z")


def test_partial_update_writes_audit_and_preserves_other_fields(
    db: Session, auth_context: tuple[TestClient, Settings]
) -> None:
    client, _settings = auth_context
    payload = _login(client)
    token = payload["access_token"]
    current = client.get("/api/v1/me/learning-profile", headers=_auth_headers(token)).json()

    response = client.put(
        "/api/v1/me/learning-profile",
        headers=_auth_headers(token),
        json={
            "expected_updated_at": current["updated_at"],
            "daily_minutes": 35,
            "goal_type": "exam",
            "target_date": "2026-12-01",
            "display_name": "  学习者  ",
            "onboarding_completed": True,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["daily_minutes"] == 35
    assert body["goal_type"] == "exam"
    assert body["target_date"] == "2026-12-01"
    assert body["study_days"] == [True] * 7
    assert body["desired_retention"] == pytest.approx(0.90)
    assert body["display_name"] == "学习者"
    assert body["onboarding_completed_at"] is not None
    assert body["updated_at"] != current["updated_at"]

    audits = list(db.scalars(select(LearningProfileAudit)).all())
    assert len(audits) == 1
    assert set(audits[0].changed_fields) >= {
        "daily_minutes",
        "goal_type",
        "target_date",
        "display_name",
        "onboarding_completed_at",
    }
    assert audits[0].before_values["daily_minutes"] == 20
    assert audits[0].after_values["daily_minutes"] == 35


def test_invalid_values_are_rejected(
    db: Session, auth_context: tuple[TestClient, Settings]
) -> None:
    client, _settings = auth_context
    payload = _login(client)
    token = payload["access_token"]
    current = client.get("/api/v1/me/learning-profile", headers=_auth_headers(token)).json()

    cases = [
        {"daily_minutes": 4},
        {"daily_minutes": 241},
        {"study_days": [False] * 7},
        {"study_days": [True] * 6},
        {"desired_retention": 0.5},
        {"subject_priorities": {"方剂学": 9}},
        {"timezone": "Mars/Olympus_Mons"},
    ]
    for patch in cases:
        response = client.put(
            "/api/v1/me/learning-profile",
            headers=_auth_headers(token),
            json={"expected_updated_at": current["updated_at"], **patch},
        )
        assert response.status_code == 422, (patch, response.text)
        assert response.json()["code"] == "VALIDATION_ERROR"

    assert db.scalar(select(func.count()).select_from(LearningProfileAudit)) == 0


def test_concurrent_update_returns_conflict(
    db: Session, auth_context: tuple[TestClient, Settings]
) -> None:
    client, _settings = auth_context
    payload = _login(client)
    token = payload["access_token"]
    current = client.get("/api/v1/me/learning-profile", headers=_auth_headers(token)).json()

    first = client.put(
        "/api/v1/me/learning-profile",
        headers=_auth_headers(token),
        json={"expected_updated_at": current["updated_at"], "daily_minutes": 40},
    )
    assert first.status_code == 200

    stale = client.put(
        "/api/v1/me/learning-profile",
        headers=_auth_headers(token),
        json={"expected_updated_at": current["updated_at"], "daily_minutes": 50},
    )
    assert stale.status_code == 409
    body = stale.json()
    assert body["code"] == "LEARNING_PROFILE_CONFLICT"
    assert "current_updated_at" in (body.get("details") or {})

    latest = client.get("/api/v1/me/learning-profile", headers=_auth_headers(token)).json()
    assert latest["daily_minutes"] == 40


def test_timezone_aware_expected_updated_at_is_required(
    db: Session, auth_context: tuple[TestClient, Settings]
) -> None:
    client, _settings = auth_context
    payload = _login(client)
    token = payload["access_token"]

    response = client.put(
        "/api/v1/me/learning-profile",
        headers=_auth_headers(token),
        json={"expected_updated_at": "2026-07-22T08:00:00", "daily_minutes": 30},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_non_utc_timezone_offset_matches_stored_utc(
    db: Session, auth_context: tuple[TestClient, Settings]
) -> None:
    client, _settings = auth_context
    payload = _login(client)
    token = payload["access_token"]
    current = client.get("/api/v1/me/learning-profile", headers=_auth_headers(token)).json()
    updated_at = datetime.fromisoformat(current["updated_at"].replace("Z", "+00:00"))
    shanghai = updated_at.astimezone(timezone(timedelta(hours=8))).isoformat()

    response = client.put(
        "/api/v1/me/learning-profile",
        headers=_auth_headers(token),
        json={
            "expected_updated_at": shanghai,
            "timezone": "UTC",
            "study_days": [True, False, True, False, True, False, True],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["timezone"] == "UTC"
    assert body["study_days"] == [True, False, True, False, True, False, True]


def test_dev_token_can_read_and_update_profile() -> None:
    settings = Settings(
        environment=AppEnvironment.DEVELOPMENT,
        auth_mode=AuthMode.DEV_TOKEN,
        api_token="test-token",
    )
    from app.config import get_settings

    with Session(engine) as session:
        _clean_identity_rows(session)
        create_owner_with_default_profile(session, OwnerCreate(display_name="Dev Owner"))

    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            headers = {"Authorization": "Bearer test-token", "X-Request-ID": "req_dev_profile"}
            current = client.get("/api/v1/me/learning-profile", headers=headers)
            assert current.status_code == 200
            body = current.json()
            assert body["display_name"] == "Dev Owner"

            updated = client.put(
                "/api/v1/me/learning-profile",
                headers=headers,
                json={
                    "expected_updated_at": body["updated_at"],
                    "daily_minutes": 25,
                    "subject_priorities": {"方剂学": 5},
                },
            )
            assert updated.status_code == 200, updated.text
            assert updated.json()["daily_minutes"] == 25
            assert updated.json()["subject_priorities"] == {"方剂学": 5}
    finally:
        app.dependency_overrides.pop(get_settings, None)
        with Session(engine) as session:
            _clean_identity_rows(session)


def test_learning_profile_update_schema_rejects_invalid_partial() -> None:
    with pytest.raises(ValidationError):
        LearningProfileUpdate(
            expected_updated_at=datetime(2026, 7, 22, 8, 0, tzinfo=UTC),
            study_days=[False] * 7,
        )
    with pytest.raises(ValidationError):
        LearningProfileUpdate(
            expected_updated_at=datetime(2026, 7, 22, 8, 0),
            daily_minutes=20,
        )
