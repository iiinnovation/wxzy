from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .catalog.models import Book as Book
from .catalog.models import Card as Card
from .db import Base


class ReviewState(Base):
    __tablename__ = "review_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id"), unique=True, index=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    stability: Mapped[float] = mapped_column(Float, default=1.0)
    difficulty: Mapped[float] = mapped_column(Float, default=5.0)
    elapsed_days: Mapped[float] = mapped_column(Float, default=0.0)
    scheduled_days: Mapped[float] = mapped_column(Float, default=0.0)
    reps: Mapped[int] = mapped_column(Integer, default=0)
    lapses: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(32), default="new")  # new|learning|review|relearning
    algorithm_version: Mapped[str] = mapped_column(String(32), default="fsrs-v1")
    last_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    card: Mapped[Card] = relationship(back_populates="review_state")


class ReviewLog(Base):
    __tablename__ = "review_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id"), index=True)
    rating: Mapped[int] = mapped_column(Integer)  # 1 again 2 hard 3 good 4 easy
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    due_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stability_after: Mapped[float | None] = mapped_column(Float, nullable=True)
    difficulty_after: Mapped[float | None] = mapped_column(Float, nullable=True)
    algorithm_version: Mapped[str] = mapped_column(String(32), default="fsrs-v1")
    state_before: Mapped[str | None] = mapped_column(String(32), nullable=True)
    state_after: Mapped[str | None] = mapped_column(String(32), nullable=True)


# Alembic and test schema creation import this legacy registry module. Loading each domain model
# here keeps one SQLAlchemy metadata registry while modules are migrated incrementally.
from .identity import models as _identity_models  # noqa: E402,F401
