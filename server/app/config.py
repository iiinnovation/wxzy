from enum import StrEnum
from functools import lru_cache
from typing import Self

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DEV_API_TOKEN = "dev-token-change-me"
DEFAULT_SESSION_TTL_SECONDS = 30 * 24 * 60 * 60


class AppEnvironment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class AuthMode(StrEnum):
    DEV_TOKEN = "dev_token"
    WECHAT = "wechat"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        extra="ignore",
        hide_input_in_errors=True,
        populate_by_name=True,
    )

    app_name: str = "wxzy-card-api"
    environment: AppEnvironment = Field(
        default=AppEnvironment.DEVELOPMENT,
        validation_alias=AliasChoices("APP_ENV", "ENVIRONMENT"),
    )
    auth_mode: AuthMode = AuthMode.DEV_TOKEN
    # Local default: SQLite. Docker/prod: postgresql+psycopg://wxzy:wxzy@db:5432/wxzy
    database_url: str = Field(default="sqlite+pysqlite:///./wxzy.db", repr=False)
    api_token: str = Field(default=DEFAULT_DEV_API_TOKEN, repr=False)
    wechat_app_id: str = Field(
        default="",
        max_length=64,
        validation_alias=AliasChoices("WECHAT_APP_ID", "WECHAT_APPID"),
    )
    wechat_app_secret: str = Field(
        default="",
        max_length=256,
        repr=False,
        validation_alias=AliasChoices("WECHAT_APP_SECRET", "WECHAT_SECRET"),
    )
    session_ttl_seconds: int = Field(
        default=DEFAULT_SESSION_TTL_SECONDS,
        gt=0,
        le=365 * 24 * 60 * 60,
        validation_alias=AliasChoices("SESSION_TTL_SECONDS", "SESSION_TTL"),
    )
    cors_origins: str = "*"
    algorithm_version: str = "fsrs-v1"

    @field_validator("environment", "auth_mode", mode="before")
    @classmethod
    def normalize_mode(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip().lower()
        return {"dev": "development", "prod": "production", "testing": "test"}.get(
            normalized, normalized
        )

    @field_validator("api_token", "wechat_app_id", "wechat_app_secret", mode="before")
    @classmethod
    def normalize_secret_config(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_auth_configuration(self) -> Self:
        if self.environment == AppEnvironment.PRODUCTION and self.auth_mode != AuthMode.WECHAT:
            raise ValueError("production requires AUTH_MODE=wechat")
        if self.auth_mode == AuthMode.DEV_TOKEN:
            if not self.api_token:
                raise ValueError("API_TOKEN is required when AUTH_MODE=dev_token")
            return self
        if not self.wechat_app_id or not self.wechat_app_secret:
            raise ValueError("WECHAT_APP_ID and WECHAT_APP_SECRET are required in wechat mode")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
