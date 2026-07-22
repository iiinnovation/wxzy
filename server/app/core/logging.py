from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from .errors import (
    REDACTED,
    internal_error_response,
    is_sensitive_key,
    reset_request_id,
    set_request_id,
)

LOGGER_NAME = "uvicorn.error.wxzy"
logger = logging.getLogger(LOGGER_NAME)
logger.setLevel(logging.INFO)

_request_id_pattern = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,63}$")
_bearer_pattern = re.compile(r"(?i)\bbearer\s+[^\s,;]+")
_named_secret_pattern = re.compile(
    r"(?i)\b(authorization|api[_-]?token|access[_-]?token|api[_-]?key|password|secret)"
    r"\s*[:=]\s*(?:bearer\s+)?[^\s,;]+"
)
_url_query_pattern = re.compile(r"(https?://[^\s?]+)\?[^\s]+", re.IGNORECASE)


def configure_logging() -> None:
    # Structured request logs below intentionally replace query-bearing Uvicorn access logs.
    logging.getLogger("uvicorn.access").disabled = True


def sanitize_for_log(value: Any, *, key: str | None = None) -> Any:
    if key is not None and is_sensitive_key(key):
        return REDACTED
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        text = _url_query_pattern.sub(r"\1?[REDACTED]", value)
        text = _bearer_pattern.sub(f"Bearer {REDACTED}", text)
        text = _named_secret_pattern.sub(lambda match: f"{match.group(1)}={REDACTED}", text)
        return text[:500]
    if isinstance(value, Mapping):
        return {
            str(item_key): sanitize_for_log(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return [sanitize_for_log(item) for item in value]
    return f"<{type(value).__name__}>"


def log_event(event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    payload = sanitize_for_log({"event": event, **fields})
    logger.log(
        level,
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
    )


def resolve_request_id(header_value: str | None) -> str:
    if header_value and _request_id_pattern.fullmatch(header_value):
        return header_value
    return f"req_{uuid.uuid4().hex}"


async def request_context_middleware(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    request_id = resolve_request_id(request.headers.get("X-Request-ID"))
    request.state.request_id = request_id
    context_token = set_request_id(request_id)
    started_at = time.perf_counter()
    status_code = 500

    try:
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as exc:
            log_event(
                "unhandled_exception",
                level=logging.ERROR,
                request_id=request_id,
                error_type=type(exc).__name__,
            )
            response = internal_error_response(request_id=request_id)

        response.headers["X-Request-ID"] = request_id
        route = request.scope.get("path", request.url.path)
        log_event(
            "request_completed",
            request_id=request_id,
            method=request.method,
            route=route,
            status=status_code,
            duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
        )
        return response
    finally:
        reset_request_id(context_token)
