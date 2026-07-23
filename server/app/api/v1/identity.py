from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from ...auth import require_owner, security
from ...config import AuthMode, Settings, get_settings
from ...core.errors import InvalidRequestError
from ...db import get_db
from ...identity.auth import (
    AuthSessionResult,
    OwnerBindingConflictError,
    SessionConflictError,
    SessionInvalidError,
    login_with_openid,
    refresh_session,
    revoke_session,
)
from ...identity.models import User
from ...identity.schemas_auth import OwnerOut, SessionTokenOut, WeChatLoginIn
from ...identity.wechat import (
    UrllibWeChatCodeExchange,
    WeChatCodeError,
    WeChatCodeExchange,
    WeChatProviderError,
    WeChatUnavailableError,
)

router = APIRouter(tags=["identity"])


def get_wechat_client(settings: Settings = Depends(get_settings)) -> WeChatCodeExchange:
    return UrllibWeChatCodeExchange(
        app_id=settings.wechat_app_id,
        app_secret=settings.wechat_app_secret,
        timeout_seconds=settings.wechat_timeout_seconds,
    )


def _require_wechat_mode(settings: Settings) -> None:
    if settings.auth_mode != AuthMode.WECHAT:
        raise InvalidRequestError(
            code="AUTH_MODE_MISMATCH",
            message="微信认证未启用",
        )


def _require_credentials(
    credentials: HTTPAuthorizationCredentials | None,
) -> HTTPAuthorizationCredentials:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials


def _session_out(result: AuthSessionResult) -> SessionTokenOut:
    return SessionTokenOut(
        access_token=result.token,
        expires_at=result.expires_at,
        owner=OwnerOut.model_validate(result.owner, from_attributes=True),
    )


@router.post("/auth/wechat", response_model=SessionTokenOut)
def wechat_login(
    body: WeChatLoginIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    client: WeChatCodeExchange = Depends(get_wechat_client),
) -> SessionTokenOut:
    _require_wechat_mode(settings)
    try:
        identity = client.exchange(body.code)
        result = login_with_openid(
            db,
            openid=identity.openid,
            session_ttl_seconds=settings.session_ttl_seconds,
            device_label=body.device_label,
        )
    except WeChatCodeError as exc:
        raise InvalidRequestError(
            code="WECHAT_CODE_INVALID",
            message="微信登录凭证无效或已过期",
        ) from exc
    except WeChatUnavailableError as exc:
        raise InvalidRequestError(
            code="WECHAT_UNAVAILABLE",
            message="微信登录服务暂时不可用",
            status_code=503,
        ) from exc
    except WeChatProviderError as exc:
        raise InvalidRequestError(
            code="WECHAT_PROVIDER_ERROR",
            message="微信登录失败",
            status_code=502,
        ) from exc
    except OwnerBindingConflictError as exc:
        raise InvalidRequestError(
            code="OWNER_ALREADY_BOUND",
            message="此学习账户已绑定其他微信身份",
            status_code=403,
        ) from exc
    except SessionConflictError as exc:
        raise InvalidRequestError(
            code="SESSION_CONFLICT",
            message="登录会话创建冲突，请重试",
            status_code=409,
        ) from exc
    return _session_out(result)


@router.post("/auth/refresh", response_model=SessionTokenOut)
def refresh_auth_session(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SessionTokenOut:
    _require_wechat_mode(settings)
    token = _require_credentials(credentials).credentials
    try:
        result = refresh_session(
            db,
            token=token,
            session_ttl_seconds=settings.session_ttl_seconds,
        )
    except SessionInvalidError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid session",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except SessionConflictError as exc:
        raise InvalidRequestError(
            code="SESSION_CONFLICT",
            message="会话刷新冲突，请重新登录",
            status_code=409,
        ) from exc
    return _session_out(result)


@router.post("/auth/logout", status_code=204)
def logout_auth_session(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    _require_wechat_mode(settings)
    token = _require_credentials(credentials).credentials
    try:
        revoke_session(db, token=token)
    except SessionInvalidError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid session",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return Response(status_code=204)


@router.get("/me", response_model=OwnerOut)
def get_me(owner: User = Depends(require_owner)) -> OwnerOut:
    return OwnerOut.model_validate(owner, from_attributes=True)
