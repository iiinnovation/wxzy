from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.types import UTCDateTime
from ..db import Base

if TYPE_CHECKING:
    from ..catalog.models import Card
    from ..identity.models import User


class CardEnrollment(Base):
    __tablename__ = "card_enrollments"
    __table_args__ = (
        UniqueConstraint("user_id", "card_id", name="uq_card_enrollments_user_card"),
        CheckConstraint(
            "status IN ('queued', 'active', 'suspended', 'retired')",
            name="ck_card_enrollments_status",
        ),
        CheckConstraint(
            "source IN ('manual', 'chapter', 'plan')", name="ck_card_enrollments_source"
        ),
        CheckConstraint("priority BETWEEN 0 AND 100", name="ck_card_enrollments_priority"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(16), default="queued", server_default="queued", index=True
    )
    priority: Mapped[int] = mapped_column(Integer, default=50, server_default="50")
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    introduced_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship("User")
    card: Mapped[Card] = relationship("Card")


class CardReviewState(Base):
    __tablename__ = "card_review_states"
    __table_args__ = (
        UniqueConstraint("user_id", "card_id", name="uq_card_review_states_user_card"),
        CheckConstraint(
            "state IN ('new', 'learning', 'review', 'relearning')",
            name="ck_card_review_states_state",
        ),
        CheckConstraint(
            "last_rating IS NULL OR last_rating BETWEEN 1 AND 4",
            name="ck_card_review_states_last_rating",
        ),
        CheckConstraint("stability >= 0", name="ck_card_review_states_stability"),
        CheckConstraint(
            "difficulty >= 1 AND difficulty <= 10", name="ck_card_review_states_difficulty"
        ),
        CheckConstraint("elapsed_days >= 0", name="ck_card_review_states_elapsed_days"),
        CheckConstraint("scheduled_days >= 0", name="ck_card_review_states_scheduled_days"),
        CheckConstraint("reps >= 0", name="ck_card_review_states_reps"),
        CheckConstraint("lapses >= 0", name="ck_card_review_states_lapses"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    due_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    stability: Mapped[float] = mapped_column(Float, default=1.0, server_default="1.0")
    difficulty: Mapped[float] = mapped_column(Float, default=5.0, server_default="5.0")
    elapsed_days: Mapped[float] = mapped_column(Float, default=0.0, server_default="0.0")
    scheduled_days: Mapped[float] = mapped_column(Float, default=0.0, server_default="0.0")
    reps: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    lapses: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    state: Mapped[str] = mapped_column(String(16), default="new", server_default="new")
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    last_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship("User")
    card: Mapped[Card] = relationship("Card")
