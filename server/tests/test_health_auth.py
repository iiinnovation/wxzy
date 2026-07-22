from collections.abc import Iterator
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def test_health_is_public(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["app"] == "wxzy-card-api"
    assert datetime.fromisoformat(payload["time"]).tzinfo is not None


def test_protected_endpoint_requires_bearer_token(client: TestClient) -> None:
    response = client.get("/books", headers={"X-Request-ID": "req_missing_401"})

    assert response.status_code == 401
    payload = response.json()
    assert payload == {
        "code": "UNAUTHORIZED",
        "message": "连接凭证无效",
        "request_id": "req_missing_401",
        "details": None,
    }
    assert response.headers["X-Request-ID"] == "req_missing_401"
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_protected_endpoint_rejects_wrong_token(client: TestClient) -> None:
    response = client.get(
        "/books",
        headers={
            "Authorization": "Bearer wrong-token",
            "X-Request-ID": "req_wrong_401",
        },
    )

    assert response.status_code == 401
    assert response.json() == {
        "code": "UNAUTHORIZED",
        "message": "连接凭证无效",
        "request_id": "req_wrong_401",
        "details": None,
    }


def test_protected_endpoint_accepts_configured_token(client: TestClient) -> None:
    response = client.get("/books", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    assert response.json() == []
