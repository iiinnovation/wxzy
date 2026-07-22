from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from contextvars import ContextVar, Token
from typing import Any

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

REDACTED = "[REDACTED]"

_request_id: ContextVar[str] = ContextVar("request_id", default="req_unknown")
_sensitive_key_fragments = {
    "authorization",
    "token",
    "secret",
    "password",
    "apikey",
    "openid",
    "sourceexcerpt",
    "originaltext",
    "rawtext",
    "modelcontext",
    "原文",
}


def set_request_id(value: str) -> Token[str]:
    return _request_id.set(value)


def reset_request_id(token: Token[str]) -> None:
    _request_id.reset(token)


def get_request_id() -> str:
    return _request_id.get()


def is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", key.casefold())
    return any(fragment in normalized for fragment in _sensitive_key_fragments)


def sanitize_error_details(value: Any, *, key: str | None = None) -> Any:
    if key is not None and is_sensitive_key(key):
        return REDACTED
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return value[:500]
    if isinstance(value, Mapping):
        return {
            str(item_key): sanitize_error_details(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return [sanitize_error_details(item) for item in value]
    return None


class AppError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


class ResourceNotFoundError(AppError):
    def __init__(self, *, code: str, message: str, details: Any = None) -> None:
        super().__init__(code=code, message=message, status_code=404, details=details)


class InvalidRequestError(AppError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        details: Any = None,
        status_code: int = 400,
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=status_code,
            details=details,
        )


_http_defaults: dict[int, tuple[str, str]] = {
    400: ("BAD_REQUEST", "请求无效"),
    401: ("UNAUTHORIZED", "连接凭证无效"),
    403: ("FORBIDDEN", "没有访问权限"),
    404: ("NOT_FOUND", "请求的资源不存在"),
    405: ("METHOD_NOT_ALLOWED", "请求方法不受支持"),
    409: ("CONFLICT", "请求与当前状态冲突"),
    422: ("VALIDATION_ERROR", "请求参数无效"),
    429: ("TOO_MANY_REQUESTS", "请求过于频繁"),
}


def error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    request_id: str | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    resolved_request_id = request_id or get_request_id()
    return JSONResponse(
        status_code=status_code,
        content={
            "code": code,
            "message": message,
            "request_id": resolved_request_id,
            "details": sanitize_error_details(details),
        },
        headers=dict(headers or {}),
    )


def internal_error_response(*, request_id: str | None = None) -> JSONResponse:
    return error_response(
        status_code=500,
        code="INTERNAL_ERROR",
        message="服务器内部错误",
        request_id=request_id,
    )


async def app_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


async def http_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code, message = _http_defaults.get(
        exc.status_code,
        ("HTTP_ERROR", "请求处理失败" if exc.status_code < 500 else "服务器内部错误"),
    )
    return error_response(
        status_code=exc.status_code,
        code=code,
        message=message,
        headers=exc.headers,
    )


async def validation_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    details = [
        {
            "location": [str(part) for part in error.get("loc", ())],
            "message": str(error.get("msg") or "参数无效")[:200],
            "type": str(error.get("type") or "validation_error"),
        }
        for error in exc.errors()
    ]
    return error_response(
        status_code=422,
        code="VALIDATION_ERROR",
        message="请求参数无效",
        details=details,
    )


async def integrity_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, IntegrityError)
    return error_response(
        status_code=409,
        code="DATABASE_CONFLICT",
        message="数据与当前状态冲突",
    )


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
