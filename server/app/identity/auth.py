from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from .models import User, UserSession
from .services import build_default_learning_profile


class OwnerBindingConflictError(RuntimeError):
    pass


class SessionInvalidError(RuntimeError):
    pass


class SessionConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class AuthSessionResult:
    token: str
    expires_at: datetime
    owner: User


@dataclass(frozen=True)
class AuthenticatedSession:
    session: UserSession
    owner: User


def utc_now() -> datetime:
    return datetime.now(UTC)


def require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime values must include a timezone")
    return value.astimezone(UTC)


def hash_openid(openid: str) -> str:
    normalized = openid.strip()
    if not normalized or len(normalized) > 128:
        raise ValueError("openid must contain 1 to 128 characters")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def hash_session_token(token: str) -> str:
    if not token:
        raise ValueError("session token must not be empty")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_session_token() -> str:
    return secrets.token_urlsafe(32)


def _session_query(token: str):
    return (
        select(UserSession)
        .options(joinedload(UserSession.user))
        .join(User)
        .where(UserSession.token_hash == hash_session_token(token))
        .limit(1)
    )


def get_authenticated_session(
    db: Session,
    *,
    token: str,
    now: datetime | None = None,
) -> AuthenticatedSession:
    timestamp = require_aware_utc(now or utc_now())
    session = db.scalar(_session_query(token))
    if (
        session is None
        or session.revoked_at is not None
        or session.expires_at <= timestamp
        or session.user.status != "active"
    ):
        raise SessionInvalidError
    return AuthenticatedSession(session=session, owner=session.user)


def login_with_openid(
    db: Session,
    *,
    openid: str,
    session_ttl_seconds: int,
    device_label: str | None = None,
    now: datetime | None = None,
    token_factory: Callable[[], str] = _new_session_token,
) -> AuthSessionResult:
    timestamp = require_aware_utc(now or utc_now())
    openid_hash = hash_openid(openid)
    if session_ttl_seconds <= 0:
        raise ValueError("session_ttl_seconds must be positive")
    try:
        existing_owner = db.scalar(
            select(User).where(User.status == "active").order_by(User.id).limit(1).with_for_update()
        )
        bound_owner = db.scalar(
            select(User).where(User.wechat_openid_hash == openid_hash).limit(1).with_for_update()
        )
        if bound_owner is not None and bound_owner.status != "active":
            raise OwnerBindingConflictError
        if existing_owner is not None:
            if (
                existing_owner.wechat_openid_hash is not None
                and existing_owner.wechat_openid_hash != openid_hash
            ):
                raise OwnerBindingConflictError
            owner = existing_owner
            owner.wechat_openid_hash = openid_hash
            owner.updated_at = timestamp
        elif bound_owner is not None:
            owner = bound_owner
            owner.updated_at = timestamp
        else:
            owner = User(
                status="active",
                wechat_openid_hash=openid_hash,
                timezone="Asia/Shanghai",
                created_at=timestamp,
                updated_at=timestamp,
            )
            db.add(owner)
            db.flush()
            owner.learning_profile = build_default_learning_profile(owner.id, now=timestamp)

        if owner.learning_profile is None:
            db.add(build_default_learning_profile(owner.id, now=timestamp))

        token = token_factory()
        expires_at = timestamp + timedelta(seconds=session_ttl_seconds)
        db.add(
            UserSession(
                user_id=owner.id,
                token_hash=hash_session_token(token),
                expires_at=expires_at,
                device_label=device_label,
                created_at=timestamp,
            )
        )
        db.commit()
    except OwnerBindingConflictError:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise SessionConflictError from exc
    except Exception:
        db.rollback()
        raise
    db.refresh(owner)
    return AuthSessionResult(token=token, expires_at=expires_at, owner=owner)


def refresh_session(
    db: Session,
    *,
    token: str,
    session_ttl_seconds: int,
    now: datetime | None = None,
    token_factory: Callable[[], str] = _new_session_token,
) -> AuthSessionResult:
    timestamp = require_aware_utc(now or utc_now())
    if session_ttl_seconds <= 0:
        raise ValueError("session_ttl_seconds must be positive")
    try:
        authenticated = get_authenticated_session(db, token=token, now=timestamp)
        new_token = token_factory()
        authenticated.session.token_hash = hash_session_token(new_token)
        expires_at = timestamp + timedelta(seconds=session_ttl_seconds)
        authenticated.session.expires_at = expires_at
        db.commit()
    except SessionInvalidError:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise SessionConflictError from exc
    except Exception:
        db.rollback()
        raise
    db.refresh(authenticated.owner)
    return AuthSessionResult(token=new_token, expires_at=expires_at, owner=authenticated.owner)


def revoke_session(
    db: Session,
    *,
    token: str,
    now: datetime | None = None,
) -> None:
    timestamp = require_aware_utc(now or utc_now())
    session = db.scalar(_session_query(token))
    if session is None:
        db.rollback()
        raise SessionInvalidError
    if session.revoked_at is None:
        session.revoked_at = timestamp
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
