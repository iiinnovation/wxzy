from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.v1.identity import get_wechat_client
from app.config import AppEnvironment, AuthMode, Settings
from app.db import engine
from app.identity.auth import hash_openid, hash_session_token
from app.identity.models import LearningProfile, User, UserSession
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

    payload = _login(client)
    db.expire_all()

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
    stored_owner = db.get(User, owner_id)
    assert stored_owner is not None
    assert stored_owner.wechat_openid_hash == hash_openid("openid-primary")
    assert "openid-primary" not in stored_owner.wechat_openid_hash
    session = db.scalar(select(UserSession).where(UserSession.user_id == owner_id))
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
