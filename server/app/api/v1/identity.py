from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from ...auth import require_owner, security
from ...config import AuthMode, Settings, get_settings
from ...core.errors import InvalidRequestError, ResourceNotFoundError
from ...db import get_db
from ...identity.account import (
    OwnerAccountReferenceError,
    delete_owner_account,
    export_owner_learning_data,
    learning_profile_values,
    list_owner_sessions,
    revoke_owner_session,
)
from ...identity.auth import (
    AuthSessionResult,
    MobileActivationInvalidError,
    OwnerBindingConflictError,
    SessionConflictError,
    SessionInvalidError,
    activate_owner_device,
    get_authenticated_session,
    login_with_openid,
    refresh_session,
    revoke_session,
)
from ...identity.models import User
from ...identity.schemas import LearningProfileOut, LearningProfileUpdate
from ...identity.schemas_auth import (
    AccountDeleteIn,
    MobileActivateIn,
    OwnerDataExportOut,
    OwnerOut,
    SessionDeviceListOut,
    SessionTokenOut,
    WeChatLoginIn,
)
from ...identity.services import (
    LearningProfileConflictError,
    LearningProfileNotFoundError,
    apply_learning_profile_update,
    get_learning_profile,
)
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


def _current_session_id(
    *,
    credentials: HTTPAuthorizationCredentials | None,
    settings: Settings,
    db: Session,
) -> int | None:
    if settings.auth_mode != AuthMode.WECHAT or credentials is None:
        return None
    try:
        return get_authenticated_session(db, token=credentials.credentials).session.id
    except SessionInvalidError:
        # The session was revoked/expired between require_owner and this lookup;
        # simply mark no session as current rather than failing the request.
        return None


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


@router.post("/auth/mobile/activate", response_model=SessionTokenOut)
def mobile_activate(
    body: MobileActivateIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SessionTokenOut:
    _require_wechat_mode(settings)
    try:
        result = activate_owner_device(
            db,
            activation_code=body.activation_code,
            session_ttl_seconds=settings.session_ttl_seconds,
            device_label=body.device_label,
        )
    except MobileActivationInvalidError as exc:
        raise InvalidRequestError(
            code="MOBILE_ACTIVATION_INVALID",
            message="设备激活码无效或已过期",
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


@router.get("/me/sessions", response_model=SessionDeviceListOut)
def get_my_sessions(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    settings: Settings = Depends(get_settings),
    owner: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> SessionDeviceListOut:
    current_session_id = _current_session_id(
        credentials=credentials,
        settings=settings,
        db=db,
    )
    return SessionDeviceListOut(
        items=list_owner_sessions(
            db,
            user_id=owner.id,
            current_session_id=current_session_id,
        )
    )


@router.delete("/me/sessions/{session_id}", status_code=204)
def delete_my_session(
    session_id: int,
    owner: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> Response:
    try:
        revoke_owner_session(db, user_id=owner.id, session_id=session_id)
    except OwnerAccountReferenceError as exc:
        raise ResourceNotFoundError(
            code="SESSION_NOT_FOUND",
            message="登录设备不存在",
        ) from exc
    return Response(status_code=204)


@router.get("/me/export", response_model=OwnerDataExportOut)
def export_my_data(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    settings: Settings = Depends(get_settings),
    owner: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> OwnerDataExportOut:
    try:
        profile = get_learning_profile(db, user_id=owner.id)
    except LearningProfileNotFoundError as exc:
        raise ResourceNotFoundError(
            code="LEARNING_PROFILE_NOT_FOUND",
            message="学习档案不存在",
        ) from exc
    current_session_id = _current_session_id(
        credentials=credentials,
        settings=settings,
        db=db,
    )
    return OwnerDataExportOut(
        generated_at=datetime.now(UTC),
        owner=OwnerOut.model_validate(owner, from_attributes=True),
        learning_profile=learning_profile_values(profile),
        sessions=list_owner_sessions(
            db,
            user_id=owner.id,
            current_session_id=current_session_id,
        ),
        learning_data=export_owner_learning_data(db, user_id=owner.id),
    )


@router.delete("/me", status_code=204)
def delete_my_data(
    body: AccountDeleteIn | None = None,
    confirmation: str | None = None,
    owner: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> Response:
    # wx.request drops DELETE bodies on some platforms (e.g. PC WeChat), so the
    # confirmation may arrive as a query parameter instead of the JSON body.
    value = body.confirmation if body is not None else confirmation
    if value != "DELETE_MY_DATA":
        raise InvalidRequestError(
            code="ACCOUNT_DELETE_CONFIRMATION_INVALID",
            message="confirmation must be DELETE_MY_DATA",
            status_code=422,
        )
    delete_owner_account(db, user_id=owner.id)
    return Response(status_code=204)


@router.get("/me/learning-profile", response_model=LearningProfileOut)
def get_my_learning_profile(
    owner: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> LearningProfileOut:
    try:
        profile = get_learning_profile(db, user_id=owner.id)
    except LearningProfileNotFoundError as exc:
        raise ResourceNotFoundError(
            code="LEARNING_PROFILE_NOT_FOUND",
            message="学习档案不存在",
        ) from exc
    return LearningProfileOut.from_entities(profile, owner)


@router.put("/me/learning-profile", response_model=LearningProfileOut)
def put_my_learning_profile(
    body: LearningProfileUpdate,
    owner: User = Depends(require_owner),
    db: Session = Depends(get_db),
) -> LearningProfileOut:
    try:
        profile = apply_learning_profile_update(db, owner=owner, update=body)
    except LearningProfileNotFoundError as exc:
        raise ResourceNotFoundError(
            code="LEARNING_PROFILE_NOT_FOUND",
            message="学习档案不存在",
        ) from exc
    except LearningProfileConflictError as exc:
        raise InvalidRequestError(
            code="LEARNING_PROFILE_CONFLICT",
            message="学习档案已被其他请求更新，请刷新后重试",
            status_code=409,
            details={"current_updated_at": exc.current_updated_at.isoformat()},
        ) from exc
    return LearningProfileOut.from_entities(profile, owner)
