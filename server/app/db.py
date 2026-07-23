from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args: dict[str, object] = {}
engine_kwargs: dict[str, object] = {"pool_pre_ping": True}

if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
    # Shared in-memory SQLite (tests) needs a single persistent connection.
    # QueuePool can recycle/close the only connection and surface
    # "Cannot operate on a closed database" under full-suite coverage.
    if ":memory:" in settings.database_url or "mode=memory" in settings.database_url:
        engine_kwargs["poolclass"] = StaticPool

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    **engine_kwargs,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
