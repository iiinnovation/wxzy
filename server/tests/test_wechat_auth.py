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
from app.identity.auth import hash_openid, hash_session_token
from app.identity.models import LearningProfile, LearningProfileAudit, User, UserSession
from app.identity.schemas import OwnerCreate
from app.identity.services import create_owner_with_default_profile
from app.identity.wechat import (
    UrllibWeChatCodeExchange,
    WeChatCodeError,
    WeChatIdentity,
    WeChatProviderError,
    WeChatUnavailableError,
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
from app.main import app


def _clean_identity_rows(db: Session) -> None:
    db.execute(delete(ReviewAttempt))
    db.execute(delete(CardIssue))
    db.execute(delete(StudySession))
    db.execute(delete(DailyPlanItem))
    db.execute(delete(DailyPlan))
    db.execute(delete(CardReviewState))
    db.execute(delete(CardEnrollment))
    db.execute(delete(LearningProfileAudit))
    db.execute(delete(LearningProfile))
    db.execute(delete(UserSession))
    db.execute(delete(User))
    db.commit()


@pytest.fixture
def db() -> Iterator[Session]:
    with Session(engine) as session:
        _clean_identity_rows(session)
        yield session
        session.rollback()
        _clean_identity_rows(session)


class FakeWeChatClient:
    def __init__(self) -> None:
        self.identities = {
            "valid-code": "openid-primary",
            "same-code": "openid-primary",
            "other-code": "openid-other",
        }
        self.failures: dict[str, Exception] = {}

    def exchange(self, code: str) -> WeChatIdentity:
        failure = self.failures.get(code)
        if failure is not None:
            raise failure
        openid = self.identities.get(code)
        if openid is None:
            raise WeChatCodeError()
        return WeChatIdentity(openid=openid)


@pytest.fixture
def auth_context(db: Session) -> Iterator[tuple[TestClient, FakeWeChatClient, Settings]]:
    settings = Settings(
        environment=AppEnvironment.TEST,
        auth_mode=AuthMode.WECHAT,
        wechat_app_id="wx-test-app",
        wechat_app_secret="wechat-test-secret",
        session_ttl_seconds=3600,
    )
    fake = FakeWeChatClient()
    app.dependency_overrides[get_wechat_client] = lambda: fake
    from app.config import get_settings

    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, fake, settings
    app.dependency_overrides.pop(get_wechat_client, None)
    app.dependency_overrides.pop(get_settings, None)


def _login(client: TestClient, code: str = "valid-code") -> dict[str, Any]:
    response = client.post(
        "/api/v1/auth/wechat",
        json={"code": code, "device_label": "test device"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_first_login_claims_existing_legacy_owner_and_never_returns_openid(
    db: Session,
    auth_context: tuple[TestClient, FakeWeChatClient, Settings],
) -> None:
    client, _fake, _settings = auth_context
    owner = create_owner_with_default_profile(
        db,
        data=OwnerCreate(display_name="Existing Owner"),
    )
    owner_id = owner.id
    # Detach fixture-owned row so later asserts do not reload through a
    # connection that may have been recycled by concurrent request sessions.
    db.expunge(owner)
    db.commit()

    payload = _login(client)

    assert payload["owner"] == {
        "id": owner_id,
        "status": "active",
        "display_name": "Existing Owner",
        "timezone": "Asia/Shanghai",
    }
    assert "openid" not in payload
    assert "session_key" not in payload
    token = payload["access_token"]
    assert token and len(token) >= 32
    # Read post-login state on a fresh session: request handlers close their own
    # SessionLocal after commit; reusing an expired fixture identity map is brittle
    # under shared in-memory SQLite + full-suite coverage.
    with Session(engine) as verify:
        stored_owner = verify.get(User, owner_id)
        assert stored_owner is not None
        assert stored_owner.wechat_openid_hash == hash_openid("openid-primary")
        assert "openid-primary" not in stored_owner.wechat_openid_hash
        session = verify.scalar(select(UserSession).where(UserSession.user_id == owner_id))
        assert session is not None
        assert session.token_hash == hash_session_token(token)
        assert session.expires_at > datetime.now(UTC)

    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["id"] == owner_id


def test_first_login_creates_owner_and_repeated_login_reuses_it(
    db: Session,
    auth_context: tuple[TestClient, FakeWeChatClient, Settings],
) -> None:
    client, _fake, _settings = auth_context

    first = _login(client)
    second = _login(client, "same-code")

    assert first["owner"]["id"] == second["owner"]["id"]
    assert db.scalar(select(func.count()).select_from(User)) == 1
    assert db.scalar(select(func.count()).select_from(LearningProfile)) == 1
    assert db.scalar(select(func.count()).select_from(UserSession)) == 2


def test_different_openid_is_rejected_without_creating_a_session(
    db: Session,
    auth_context: tuple[TestClient, FakeWeChatClient, Settings],
) -> None:
    client, _fake, _settings = auth_context
    _login(client)

    response = client.post("/api/v1/auth/wechat", json={"code": "other-code"})

    assert response.status_code == 403
    assert response.json()["code"] == "OWNER_ALREADY_BOUND"
    assert db.scalar(select(func.count()).select_from(UserSession)) == 1


@pytest.mark.parametrize(
    ("code", "status_code", "error_code"),
    [
        ("expired-code", 400, "WECHAT_CODE_INVALID"),
        ("timeout-code", 503, "WECHAT_UNAVAILABLE"),
        ("provider-code", 502, "WECHAT_PROVIDER_ERROR"),
    ],
)
def test_code_exchange_failures_have_stable_safe_errors(
    auth_context: tuple[TestClient, FakeWeChatClient, Settings],
    code: str,
    status_code: int,
    error_code: str,
) -> None:
    client, fake, _settings = auth_context
    fake.failures = {
        "expired-code": WeChatCodeError(),
        "timeout-code": WeChatUnavailableError(),
        "provider-code": WeChatProviderError(),
    }

    response = client.post(
        "/api/v1/auth/wechat",
        json={"code": code, "device_label": "secret session_key must not appear"},
    )

    assert response.status_code == status_code
    assert response.json()["code"] == error_code
    assert "wechat-test-secret" not in response.text
    assert "session_key" not in response.text


def test_refresh_rotates_token_and_invalidates_the_old_one(
    db: Session,
    auth_context: tuple[TestClient, FakeWeChatClient, Settings],
) -> None:
    client, _fake, _settings = auth_context
    first = _login(client)
    old_token = first["access_token"]

    response = client.post(
        "/api/v1/auth/refresh",
        headers={"Authorization": f"Bearer {old_token}"},
    )

    assert response.status_code == 200
    new_token = response.json()["access_token"]
    assert new_token != old_token
    assert db.scalar(select(func.count()).select_from(UserSession)) == 1
    assert db.scalar(select(UserSession.token_hash)) == hash_session_token(new_token)
    assert (
        client.get("/api/v1/me", headers={"Authorization": f"Bearer {old_token}"}).status_code
        == 401
    )
    assert (
        client.get("/api/v1/me", headers={"Authorization": f"Bearer {new_token}"}).status_code
        == 200
    )


def test_expired_session_cannot_access_me_or_refresh(
    db: Session,
    auth_context: tuple[TestClient, FakeWeChatClient, Settings],
) -> None:
    client, _fake, _settings = auth_context
    payload = _login(client)
    session = db.scalar(select(UserSession))
    assert session is not None
    session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()

    headers = {"Authorization": f"Bearer {payload['access_token']}"}
    assert client.get("/api/v1/me", headers=headers).status_code == 401
    assert client.post("/api/v1/auth/refresh", headers=headers).status_code == 401


def test_logout_is_idempotent_and_revokes_session(
    auth_context: tuple[TestClient, FakeWeChatClient, Settings],
) -> None:
    client, _fake, _settings = auth_context
    payload = _login(client)
    headers = {"Authorization": f"Bearer {payload['access_token']}"}

    first = client.post("/api/v1/auth/logout", headers=headers)
    second = client.post("/api/v1/auth/logout", headers=headers)

    assert first.status_code == second.status_code == 204
    assert client.get("/api/v1/me", headers=headers).status_code == 401


def test_owner_can_list_and_revoke_device_sessions(
    auth_context: tuple[TestClient, FakeWeChatClient, Settings],
) -> None:
    client, _fake, _settings = auth_context
    _login(client)
    second = _login(client, "same-code")
    headers = {"Authorization": f"Bearer {second['access_token']}"}

    listed = client.get("/api/v1/me/sessions", headers=headers)

    assert listed.status_code == 200, listed.text
    sessions = listed.json()["items"]
    assert len(sessions) == 2
    assert sum(item["current"] for item in sessions) == 1
    current = next(item for item in sessions if item["current"])
    other = next(item for item in sessions if not item["current"])
    assert current["status"] == other["status"] == "active"
    assert "token_hash" not in listed.text

    revoked = client.delete(f"/api/v1/me/sessions/{other['id']}", headers=headers)
    replay = client.delete(f"/api/v1/me/sessions/{other['id']}", headers=headers)
    missing = client.delete("/api/v1/me/sessions/999999", headers=headers)

    assert revoked.status_code == replay.status_code == 204
    assert missing.status_code == 404
    refreshed = client.get("/api/v1/me/sessions", headers=headers).json()["items"]
    assert next(item for item in refreshed if item["id"] == other["id"])["status"] == "revoked"


def test_owner_export_is_versioned_and_excludes_authentication_secrets(
    db: Session,
    auth_context: tuple[TestClient, FakeWeChatClient, Settings],
) -> None:
    client, _fake, _settings = auth_context
    payload = _login(client)
    active_started_at = datetime(2026, 7, 26, 1, 0, tzinfo=UTC)
    db.add(
        StudySession(
            user_id=payload["owner"]["id"],
            session_type="daily",
            status="active",
            started_at=active_started_at,
            active_started_at=active_started_at,
            estimated_minutes=10,
            actual_minutes=0,
            planned_task_count=1,
            completed_task_count=0,
            cursor_position=0,
        )
    )
    db.commit()
    response = client.get(
        "/api/v1/me/export",
        headers={"Authorization": f"Bearer {payload['access_token']}"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema_version"] == "wxzy-owner-export-v1"
    assert body["backup_status"] == "not_configured"
    assert body["owner"]["id"] == payload["owner"]["id"]
    assert body["learning_profile"]["daily_minutes"] == 20
    assert set(body["learning_data"]) == {
        "learning_profile_audits",
        "enrollments",
        "review_states",
        "study_sessions",
        "review_attempts",
        "card_issues",
        "daily_plans",
        "daily_plan_items",
    }
    assert body["learning_data"]["study_sessions"][0]["active_started_at"] == (
        active_started_at.isoformat().replace("+00:00", "Z")
    )
    assert "token_hash" not in response.text
    assert "openid" not in response.text
    assert payload["access_token"] not in response.text


def test_owner_delete_requires_confirmation_and_removes_identity_data(
    db: Session,
    auth_context: tuple[TestClient, FakeWeChatClient, Settings],
) -> None:
    client, _fake, _settings = auth_context
    payload = _login(client)
    headers = {"Authorization": f"Bearer {payload['access_token']}"}
    owner_id = payload["owner"]["id"]
    profile = db.scalar(select(LearningProfile).where(LearningProfile.user_id == owner_id))
    assert profile is not None
    now = datetime(2026, 7, 26, 1, 0, tzinfo=UTC)
    book = Book(name="Owner deletion catalog survives", subject="测试")
    db.add(book)
    db.flush()
    card = Card(
        external_id="owner-deletion-card",
        book_id=book.id,
        card_type="definition",
        question="问题",
        answer="答案",
        source_excerpt="来源",
        status="published",
        content_revision=1,
        content_hash="d" * 64,
        answer_points=[],
        tags=[],
    )
    db.add(card)
    db.flush()
    enrollment = CardEnrollment(
        user_id=owner_id,
        card_id=card.id,
        status="active",
        priority=50,
        source="manual",
        introduced_at=now,
    )
    review_state = CardReviewState(
        user_id=owner_id,
        card_id=card.id,
        due_at=now,
        stability=1.0,
        difficulty=5.0,
        elapsed_days=0,
        scheduled_days=0,
        reps=0,
        lapses=0,
        state="new",
        algorithm_version="fsrs-6.3.0",
    )
    plan = DailyPlan(
        user_id=owner_id,
        plan_date="2026-07-26",
        budget_minutes=20,
        estimated_minutes=1,
        due_count=1,
        new_count=0,
        weak_count=0,
        generation_version="daily-plan-v1",
        is_initial=False,
        forecast_minutes_7d=0,
        forecast_budget_7d=140,
        new_cards_paused=False,
        pause_reasons=[],
        plan_reasons=["DUE_PRIORITY"],
        generated_at=now,
    )
    db.add_all([enrollment, review_state, plan])
    db.flush()
    plan_item = DailyPlanItem(
        plan_id=plan.id,
        position=0,
        item_type="due",
        enrollment_id=enrollment.id,
        card_id=card.id,
        estimated_seconds=60,
        reason_code="DUE",
        status="pending",
    )
    study_session = StudySession(
        user_id=owner_id,
        session_type="daily",
        status="active",
        started_at=now,
        active_started_at=now,
        estimated_minutes=1,
        actual_minutes=0,
        planned_task_count=1,
        completed_task_count=0,
        daily_plan_id=plan.id,
        plan_date=plan.plan_date,
        cursor_position=0,
    )
    db.add_all([plan_item, study_session])
    db.flush()
    db.add_all(
        [
            ReviewAttempt(
                session_id=study_session.id,
                user_id=owner_id,
                card_id=card.id,
                card_revision=1,
                client_attempt_id="owner-delete-attempt",
                rating=3,
                response_ms=1200,
                hint_used=False,
                reveal_count=1,
                state_before={"state": "new"},
                state_after={"state": "learning"},
                due_before=now,
                due_after=now + timedelta(days=1),
                algorithm_version="fsrs-6.3.0",
                reviewed_at=now,
            ),
            CardIssue(
                user_id=owner_id,
                card_id=card.id,
                card_revision=1,
                issue_type="unclear",
                details="测试",
                status="open",
                created_at=now,
            ),
            LearningProfileAudit(
                user_id=owner_id,
                profile_id=profile.id,
                changed_fields=["daily_minutes"],
                before_values={"daily_minutes": 20},
                after_values={"daily_minutes": 30},
                created_at=now,
            ),
        ]
    )
    db.commit()

    rejected = client.request(
        "DELETE",
        "/api/v1/me",
        headers=headers,
        json={"confirmation": "wrong"},
    )
    assert rejected.status_code == 422
    assert client.get("/api/v1/me", headers=headers).status_code == 200

    deleted = client.request(
        "DELETE",
        "/api/v1/me",
        headers=headers,
        json={"confirmation": "DELETE_MY_DATA"},
    )

    assert deleted.status_code == 204, deleted.text
    assert client.get("/api/v1/me", headers=headers).status_code == 401
    for model in (
        User,
        UserSession,
        LearningProfile,
        LearningProfileAudit,
        CardEnrollment,
        CardReviewState,
        DailyPlan,
        DailyPlanItem,
        StudySession,
        ReviewAttempt,
        CardIssue,
    ):
        assert db.scalar(select(func.count()).select_from(model)) == 0
    assert db.get(Card, card.id) is not None
    assert db.scalar(select(func.count()).select_from(UserSession)) == 0
    assert db.scalar(select(func.count()).select_from(LearningProfile)) == 0


def test_urllib_adapter_maps_provider_responses_without_persisting_session_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.identity.wechat as wechat

    class Response:
        def __init__(self, body: bytes) -> None:
            self.body = body

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _limit: int) -> bytes:
            return self.body

    monkeypatch.setattr(
        wechat,
        "urlopen",
        lambda _request, timeout: Response(
            b'{"openid":"openid-from-wechat","session_key":"not-persisted"}'
        ),
    )
    client = UrllibWeChatCodeExchange(
        app_id="wx-app",
        app_secret="app-secret",
        timeout_seconds=1,
    )

    result = client.exchange("code")

    assert result == WeChatIdentity(openid="openid-from-wechat")


@pytest.mark.parametrize(
    ("body", "exception"),
    [
        (b'{"errcode":40029,"errmsg":"invalid code"}', WeChatCodeError),
        (b'{"errcode":-1,"errmsg":"system busy"}', WeChatProviderError),
        (b"not json", WeChatProviderError),
    ],
)
def test_urllib_adapter_maps_invalid_provider_payloads(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
    exception: type[Exception],
) -> None:
    import app.identity.wechat as wechat

    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _limit: int) -> bytes:
            return body

    monkeypatch.setattr(wechat, "urlopen", lambda _request, timeout: Response())

    with pytest.raises(exception):
        UrllibWeChatCodeExchange(
            app_id="wx-app",
            app_secret="app-secret",
        ).exchange("code")


def test_urllib_adapter_maps_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.identity.wechat as wechat

    def timeout(_request: object, timeout: float) -> None:
        raise TimeoutError

    monkeypatch.setattr(wechat, "urlopen", timeout)

    with pytest.raises(WeChatUnavailableError):
        UrllibWeChatCodeExchange(app_id="wx-app", app_secret="app-secret").exchange("code")
