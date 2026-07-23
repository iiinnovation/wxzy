from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError

from app.auth import require_token
from app.config import (
    DEFAULT_DEV_API_TOKEN,
    DEFAULT_SESSION_TTL_SECONDS,
    AppEnvironment,
    AuthMode,
    Settings,
)

AUTH_ENV_KEYS = (
    "APP_ENV",
    "ENVIRONMENT",
    "AUTH_MODE",
    "API_TOKEN",
    "WECHAT_APP_ID",
    "WECHAT_APP_SECRET",
    "SESSION_TTL_SECONDS",
)
SERVER_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_auth_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in AUTH_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_development_defaults_to_explicit_dev_token_mode() -> None:
    settings = Settings()

    assert settings.environment == AppEnvironment.DEVELOPMENT
    assert settings.auth_mode == AuthMode.DEV_TOKEN
    assert settings.api_token == DEFAULT_DEV_API_TOKEN
    assert settings.session_ttl_seconds == DEFAULT_SESSION_TTL_SECONDS
    assert DEFAULT_DEV_API_TOKEN not in repr(settings)


def test_dev_token_mode_accepts_custom_test_configuration() -> None:
    settings = Settings(
        environment=AppEnvironment.TEST,
        auth_mode=AuthMode.DEV_TOKEN,
        api_token=" test-only-token ",
        session_ttl_seconds=60,
    )

    assert settings.environment == AppEnvironment.TEST
    assert settings.auth_mode == AuthMode.DEV_TOKEN
    assert settings.api_token == "test-only-token"
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="test-only-token")
    assert require_token(credentials, settings) == "test-only-token"

    invalid = HTTPAuthorizationCredentials(scheme="Bearer", credentials="错误-token")
    with pytest.raises(HTTPException) as error:
        require_token(invalid, settings)
    assert error.value.status_code == 401


def test_wechat_mode_requires_credentials_and_disables_fixed_token() -> None:
    settings = Settings(
        auth_mode=AuthMode.WECHAT,
        wechat_app_id=" wx-test-app ",
        wechat_app_secret=" wechat-test-secret ",
    )

    assert settings.wechat_app_id == "wx-test-app"
    assert settings.wechat_app_secret == "wechat-test-secret"
    assert "wechat-test-secret" not in repr(settings)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=DEFAULT_DEV_API_TOKEN)
    with pytest.raises(HTTPException) as error:
        require_token(credentials, settings)
    assert error.value.status_code == 401


@pytest.mark.parametrize(
    "values",
    [
        {"environment": "production", "auth_mode": "dev_token"},
        {
            "environment": "production",
            "auth_mode": "dev_token",
            "api_token": "custom-but-still-fixed",
        },
        {"environment": "production", "auth_mode": "wechat"},
        {
            "environment": "production",
            "auth_mode": "wechat",
            "wechat_app_id": "wx-production-app",
        },
    ],
)
def test_production_misconfiguration_is_rejected(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Settings(**values)  # type: ignore[arg-type]


def test_valid_production_wechat_configuration() -> None:
    settings = Settings(
        environment=AppEnvironment.PRODUCTION,
        auth_mode=AuthMode.WECHAT,
        wechat_app_id="wx-production-app",
        wechat_app_secret="production-secret",
        session_ttl_seconds=86_400,
    )

    assert settings.environment == AppEnvironment.PRODUCTION
    assert settings.auth_mode == AuthMode.WECHAT
    assert settings.session_ttl_seconds == 86_400


def test_validation_errors_and_repr_do_not_expose_secrets() -> None:
    secret = "must-not-appear-in-errors"
    with pytest.raises(ValidationError) as error:
        Settings(
            environment=AppEnvironment.PRODUCTION,
            auth_mode=AuthMode.WECHAT,
            wechat_app_secret=secret,
        )

    assert secret not in str(error.value)

    settings = Settings(database_url="postgresql+psycopg://user:db-password@db/wxzy")
    assert "db-password" not in repr(settings)


def test_environment_variables_use_documented_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "wechat")
    monkeypatch.setenv("WECHAT_APP_ID", "wx-env-app")
    monkeypatch.setenv("WECHAT_APP_SECRET", "env-secret")
    monkeypatch.setenv("SESSION_TTL_SECONDS", "7200")

    settings = Settings()

    assert settings.environment == AppEnvironment.PRODUCTION
    assert settings.auth_mode == AuthMode.WECHAT
    assert settings.wechat_app_id == "wx-env-app"
    assert settings.session_ttl_seconds == 7200


def test_application_startup_rejects_production_dev_token_without_leaking_it() -> None:
    secret = "production-fixed-token-must-not-leak"
    environment = os.environ.copy()
    environment.update(
        {
            "APP_ENV": "production",
            "AUTH_MODE": "dev_token",
            "API_TOKEN": secret,
        }
    )

    result = subprocess.run(
        [sys.executable, "-c", "from app.main import app"],
        cwd=SERVER_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "production requires AUTH_MODE=wechat" in output
    assert secret not in output
