from secrets import compare_digest

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import AuthMode, Settings, get_settings

security = HTTPBearer(auto_error=False)


def require_token(
    creds: HTTPAuthorizationCredentials | None = Depends(security),
    settings: Settings = Depends(get_settings),
) -> str:
    if settings.auth_mode != AuthMode.DEV_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="fixed token authentication is disabled",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not compare_digest(
        creds.credentials.encode("utf-8"),
        settings.api_token.encode("utf-8"),
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return creds.credentials
