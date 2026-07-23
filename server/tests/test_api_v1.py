import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def test_openapi_contains_versioned_and_compatibility_routes(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    versioned = {
        "/api/v1/books",
        "/api/v1/cards",
        "/api/v1/review/due",
        "/api/v1/review/answer",
        "/api/v1/stats/summary",
        "/api/v1/admin/cards/import",
        "/api/v1/admin/cards/import-seed",
    }
    compatibility = {
        "/books",
        "/cards",
        "/review/due",
        "/review/answer",
        "/stats/summary",
        "/admin/cards/import",
        "/admin/cards/import-seed",
    }

    assert "/health" in paths
    assert versioned <= paths.keys()
    assert compatibility <= paths.keys()
    for path in versioned:
        assert all(not operation.get("deprecated", False) for operation in paths[path].values())
    for path in compatibility:
        assert all(operation.get("deprecated") is True for operation in paths[path].values())

    operation_ids = [
        operation["operationId"]
        for path_item in paths.values()
        for operation in path_item.values()
        if isinstance(operation, dict) and "operationId" in operation
    ]
    assert len(operation_ids) == len(set(operation_ids))


def test_versioned_and_compatibility_books_behave_the_same(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    headers = {
        "Authorization": "Bearer test-token",
        "X-Request-ID": "req_v1_books",
    }
    with caplog.at_level(logging.INFO, logger="uvicorn.error.wxzy"):
        versioned = client.get("/api/v1/books", headers=headers)
        compatibility = client.get("/books", headers=headers)

    assert versioned.status_code == 200
    assert compatibility.status_code == 200
    assert versioned.json() == compatibility.json()
    logs = "\n".join(
        record.getMessage() for record in caplog.records if record.name == "uvicorn.error.wxzy"
    )
    assert '"route":"/api/v1/books"' in logs
    assert '"route":"/books"' in logs


def test_versioned_routes_use_the_common_error_contract(client: TestClient) -> None:
    response = client.get("/api/v1/books", headers={"X-Request-ID": "req_v1_401"})

    assert response.status_code == 401
    assert response.json() == {
        "code": "UNAUTHORIZED",
        "message": "连接凭证无效",
        "request_id": "req_v1_401",
        "details": None,
    }


@pytest.mark.parametrize(
    ("versioned_path", "compatibility_path"),
    [
        ("/api/v1/cards", "/cards"),
        ("/api/v1/review/due", "/review/due"),
        ("/api/v1/stats/summary", "/stats/summary"),
    ],
)
def test_versioned_and_compatibility_reads_match(
    client: TestClient,
    versioned_path: str,
    compatibility_path: str,
) -> None:
    headers = {
        "Authorization": "Bearer test-token",
        "X-Request-ID": "req_v1_read_parity",
    }

    versioned = client.get(versioned_path, headers=headers)
    compatibility = client.get(compatibility_path, headers=headers)

    assert versioned.status_code == compatibility.status_code == 200
    assert versioned.json() == compatibility.json()


@pytest.mark.parametrize(
    ("versioned_path", "compatibility_path", "body"),
    [
        ("/api/v1/review/answer", "/review/answer", {"card_id": 999999, "rating": 3}),
    ],
)
def test_versioned_and_compatibility_write_errors_match(
    client: TestClient,
    versioned_path: str,
    compatibility_path: str,
    body: dict[str, int],
) -> None:
    headers = {
        "Authorization": "Bearer test-token",
        "X-Request-ID": "req_v1_write_parity",
    }

    versioned = client.post(versioned_path, headers=headers, json=body)
    compatibility = client.post(compatibility_path, headers=headers, json=body)

    assert versioned.status_code == compatibility.status_code == 404
    assert versioned.json() == compatibility.json()
