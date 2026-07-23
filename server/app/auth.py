from secrets import compare_digest
from typing import NoReturn

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import AuthMode, Settings, get_settings
from .db import get_db
from .identity.auth import SessionInvalidError, get_authenticated_session
from .identity.models import User

security = HTTPBearer(auto_error=False)


def require_token(
    creds: HTTPAuthorizationCredentials | None = Depends(security),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> str:
    if creds is None or creds.scheme.lower() != "bearer":
        _raise_unauthorized("missing bearer token")
    if settings.auth_mode == AuthMode.DEV_TOKEN:
        if not compare_digest(
            creds.credentials.encode("utf-8"),
            settings.api_token.encode("utf-8"),
        ):
            _raise_unauthorized("invalid token")
        return creds.credentials
    try:
        if not isinstance(db, Session):
            _raise_unauthorized("invalid session")
        get_authenticated_session(db, token=creds.credentials)
    except SessionInvalidError:
        db.rollback()
        _raise_unauthorized("invalid session")
    return creds.credentials


def require_owner(
    creds: HTTPAuthorizationCredentials | None = Depends(security),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> User:
    token = require_token(creds, settings, db)
    if settings.auth_mode == AuthMode.WECHAT:
        return get_authenticated_session(db, token=token).owner
    owner = db.scalar(select(User).where(User.status == "active").order_by(User.id).limit(1))
    if owner is None:
        _raise_unauthorized("active Owner not found")
    return owner


def _raise_unauthorized(detail: str) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )
