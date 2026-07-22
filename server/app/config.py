from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", ".env.local"), extra="ignore")

    app_name: str = "wxzy-card-api"
    # Local default: SQLite. Docker/prod: postgresql+psycopg://wxzy:wxzy@db:5432/wxzy
    database_url: str = "sqlite+pysqlite:///./wxzy.db"
    # Local/dev single-user token. Override in production.
    api_token: str = "dev-token-change-me"
    cors_origins: str = "*"
    algorithm_version: str = "fsrs-v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
