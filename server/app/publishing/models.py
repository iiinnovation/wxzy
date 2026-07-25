from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from ..core.types import UTCDateTime
from ..db import Base


class PublicationImport(Base):
    """Idempotent record of a versioned publication package import (P5-T09)."""

    __tablename__ = "publication_imports"
    __table_args__ = (
        UniqueConstraint("publication_id", name="uq_publication_imports_publication_id"),
        CheckConstraint(
            "status IN ('validated', 'imported', 'failed', 'conflict')",
            name="ck_publication_imports_status",
        ),
        CheckConstraint("length(manifest_hash) = 64", name="ck_publication_imports_manifest_hash"),
        CheckConstraint("length(package_hash) = 64", name="ck_publication_imports_package_hash"),
        CheckConstraint(
            "schema_version >= 1",
            name="ck_publication_imports_schema_version",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    publication_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    package_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    pipeline_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    generation_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    review_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    counts: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    conflicts: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    imported_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now()
    )
