from __future__ import annotations

import json
import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.core.logging import sanitize_for_log
from app.main import app
from app.routers import books as books_router


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def auth_headers(request_id: str) -> dict[str, str]:
    return {
        "Authorization": "Bearer test-token",
        "X-Request-ID": request_id,
    }


def test_not_found_uses_stable_error_envelope(client: TestClient) -> None:
    response = client.get("/route-that-does-not-exist", headers={"X-Request-ID": "req_missing_404"})

    assert response.status_code == 404
    assert response.json() == {
        "code": "NOT_FOUND",
        "message": "请求的资源不存在",
        "request_id": "req_missing_404",
        "details": None,
    }
    assert response.headers["X-Request-ID"] == "req_missing_404"


def test_validation_error_does_not_echo_input(client: TestClient) -> None:
    response = client.post(
        "/review/answer",
        headers=auth_headers("req_validation_422"),
        json={"card_id": 1, "rating": 99, "token": "do-not-echo"},
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["code"] == "VALIDATION_ERROR"
    assert payload["request_id"] == "req_validation_422"
    assert payload["details"]
    assert "do-not-echo" not in json.dumps(payload, ensure_ascii=False)
    assert "input" not in json.dumps(payload, ensure_ascii=False)


def test_known_business_value_error_maps_to_not_found(client: TestClient) -> None:
    response = client.post(
        "/review/answer",
        headers=auth_headers("req_card_404"),
        json={"card_id": 999999, "rating": 3},
    )

    assert response.status_code == 404
    assert response.json() == {
        "code": "CARD_NOT_FOUND",
        "message": "卡片不存在或尚未发布",
        "request_id": "req_card_404",
        "details": None,
    }


def test_invalid_import_payload_uses_business_error(client: TestClient) -> None:
    response = client.post(
        "/admin/cards/import",
        headers=auth_headers("req_import_400"),
        files={"file": ("cards.json", b"{}", "application/json")},
    )

    assert response.status_code == 400
    assert response.json() == {
        "code": "INVALID_IMPORT_PAYLOAD",
        "message": "卡片导入数据格式无效",
        "request_id": "req_import_400",
        "details": None,
    }


def test_integrity_error_maps_to_conflict(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_conflict(_db: object) -> None:
        raise IntegrityError("INSERT", {}, Exception("duplicate secret-token"))

    monkeypatch.setattr(books_router, "list_books", raise_conflict)
    response = client.get("/books", headers=auth_headers("req_conflict_409"))

    assert response.status_code == 409
    assert response.json() == {
        "code": "DATABASE_CONFLICT",
        "message": "数据与当前状态冲突",
        "request_id": "req_conflict_409",
        "details": None,
    }


def test_unhandled_error_is_safe_and_logged(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def raise_unhandled(_db: object) -> None:
        raise RuntimeError("Authorization: Bearer leak-token source_excerpt=完整原文")

    monkeypatch.setattr(books_router, "list_books", raise_unhandled)
    with caplog.at_level(logging.INFO, logger="uvicorn.error.wxzy"):
        response = client.get("/books", headers=auth_headers("req_internal_500"))

    assert response.status_code == 500
    assert response.json() == {
        "code": "INTERNAL_ERROR",
        "message": "服务器内部错误",
        "request_id": "req_internal_500",
        "details": None,
    }
    records = [
        record.getMessage() for record in caplog.records if record.name == "uvicorn.error.wxzy"
    ]
    log_text = "\n".join(records)
    assert "leak-token" not in log_text
    assert "完整原文" not in log_text
    assert '"status":500' in log_text
    assert '"error_type":"RuntimeError"' in log_text


def test_log_sanitizer_redacts_sensitive_keys_and_text() -> None:
    sanitized = sanitize_for_log(
        {
            "Authorization": "Bearer abc123",
            "api_token": "secret-token",
            "source_excerpt": "完整原文",
            "message": "api_key=another-secret https://example.test/a?signature=secret",
        }
    )

    encoded = json.dumps(sanitized, ensure_ascii=False)
    assert "abc123" not in encoded
    assert "secret-token" not in encoded
    assert "another-secret" not in encoded
    assert "完整原文" not in encoded
    assert logging.getLogger("uvicorn.access").disabled is True
