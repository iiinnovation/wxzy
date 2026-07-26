from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.ext.mutable import MutableDict, MutableList
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


class StudySession(Base):
    __tablename__ = "study_sessions"
    __table_args__ = (
        CheckConstraint(
            "session_type IN ('daily', 'focused', 'review', 'onboarding')",
            name="ck_study_sessions_type",
        ),
        CheckConstraint(
            "status IN ('planned', 'active', 'completed', 'interrupted', 'cancelled')",
            name="ck_study_sessions_status",
        ),
        CheckConstraint("estimated_minutes BETWEEN 0 AND 1440", name="ck_study_sessions_estimated"),
        CheckConstraint("actual_minutes BETWEEN 0 AND 1440", name="ck_study_sessions_actual"),
        CheckConstraint("planned_task_count >= 0", name="ck_study_sessions_planned_tasks"),
        CheckConstraint("completed_task_count >= 0", name="ck_study_sessions_completed_tasks"),
        CheckConstraint(
            "completed_task_count <= planned_task_count",
            name="ck_study_sessions_completed_le_planned",
        ),
        CheckConstraint("cursor_position >= 0", name="ck_study_sessions_cursor_position"),
        UniqueConstraint("daily_plan_id", name="uq_study_sessions_daily_plan_id"),
        Index("ix_study_sessions_user_status", "user_id", "status"),
        Index("ix_study_sessions_user_plan_date", "user_id", "plan_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_type: Mapped[str] = mapped_column(String(16), default="daily", server_default="daily")
    status: Mapped[str] = mapped_column(
        String(16), default="planned", server_default="planned", index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=20, server_default="20")
    actual_minutes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    planned_task_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    completed_task_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    interruption_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    daily_plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("daily_plans.id", ondelete="SET NULL"), nullable=True, index=True
    )
    plan_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    cursor_position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    active_started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship("User")
    daily_plan: Mapped[DailyPlan | None] = relationship("DailyPlan")
    attempts: Mapped[list[ReviewAttempt]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class ReviewAttempt(Base):
    __tablename__ = "review_attempts"
    __table_args__ = (
        UniqueConstraint("user_id", "client_attempt_id", name="uq_review_attempts_user_client_id"),
        CheckConstraint("card_revision > 0", name="ck_review_attempts_card_revision"),
        CheckConstraint("rating BETWEEN 1 AND 4", name="ck_review_attempts_rating"),
        CheckConstraint(
            "response_ms BETWEEN 0 AND 86400000", name="ck_review_attempts_response_ms"
        ),
        CheckConstraint("reveal_count BETWEEN 0 AND 100", name="ck_review_attempts_reveal_count"),
        Index("ix_review_attempts_user_card", "user_id", "card_id"),
        Index("ix_review_attempts_session_id", "session_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    card_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    client_attempt_id: Mapped[str] = mapped_column(String(128), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    response_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    hint_used: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    reveal_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    answer_payload: Mapped[dict[str, object] | None] = mapped_column(
        MutableDict.as_mutable(JSON), nullable=True
    )
    state_before: Mapped[dict[str, object]] = mapped_column(MutableDict.as_mutable(JSON))
    state_after: Mapped[dict[str, object]] = mapped_column(MutableDict.as_mutable(JSON))
    due_before: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    due_after: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())

    session: Mapped[StudySession] = relationship(back_populates="attempts")
    user: Mapped[User] = relationship("User")
    card: Mapped[Card] = relationship("Card")


class CardIssue(Base):
    __tablename__ = "card_issues"
    __table_args__ = (
        CheckConstraint(
            "issue_type IN ('fact_error', 'source_error', 'too_large', 'too_difficult', "
            "'unclear', 'concept_confusion')",
            name="ck_card_issues_type",
        ),
        CheckConstraint(
            "status IN ('open', 'in_review', 'resolved', 'dismissed')",
            name="ck_card_issues_status",
        ),
        CheckConstraint("card_revision > 0", name="ck_card_issues_card_revision"),
        Index("ix_card_issues_user_status", "user_id", "status"),
        Index("ix_card_issues_card_status", "card_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    card_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    issue_type: Mapped[str] = mapped_column(String(32), nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    user: Mapped[User] = relationship("User")
    card: Mapped[Card] = relationship("Card")


class DailyPlan(Base):
    __tablename__ = "daily_plans"
    __table_args__ = (
        UniqueConstraint("user_id", "plan_date", name="uq_daily_plans_user_date"),
        CheckConstraint("budget_minutes BETWEEN 5 AND 240", name="ck_daily_plans_budget_minutes"),
        CheckConstraint(
            "adjusted_budget_minutes IS NULL OR (adjusted_budget_minutes BETWEEN 5 AND 240)",
            name="ck_daily_plans_adjusted_budget_minutes",
        ),
        CheckConstraint(
            "estimated_minutes BETWEEN 0 AND 1440", name="ck_daily_plans_estimated_minutes"
        ),
        CheckConstraint("due_count >= 0", name="ck_daily_plans_due_count"),
        CheckConstraint("new_count >= 0", name="ck_daily_plans_new_count"),
        CheckConstraint("weak_count >= 0", name="ck_daily_plans_weak_count"),
        CheckConstraint("forecast_minutes_7d >= 0", name="ck_daily_plans_forecast_minutes_7d"),
        CheckConstraint("forecast_budget_7d >= 0", name="ck_daily_plans_forecast_budget_7d"),
        Index("ix_daily_plans_user_date", "user_id", "plan_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_date: Mapped[str] = mapped_column(String(10), nullable=False)
    budget_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    adjusted_budget_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    due_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    new_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    weak_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    generation_version: Mapped[str] = mapped_column(String(32), nullable=False)
    is_initial: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    forecast_minutes_7d: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    forecast_budget_7d: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    new_cards_paused: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    pause_reasons: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON), default=list, server_default=text("'[]'")
    )
    plan_reasons: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON), default=list, server_default=text("'[]'")
    )
    generated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship("User")
    items: Mapped[list[DailyPlanItem]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="DailyPlanItem.position",
    )


class DailyPlanItem(Base):
    __tablename__ = "daily_plan_items"
    __table_args__ = (
        UniqueConstraint("plan_id", "position", name="uq_daily_plan_items_plan_position"),
        UniqueConstraint("plan_id", "card_id", name="uq_daily_plan_items_plan_card"),
        CheckConstraint(
            "item_type IN ('due', 'overdue', 'new', 'weak_topic', 'repair', 'mixed_weekly')",
            name="ck_daily_plan_items_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'completed', 'skipped')",
            name="ck_daily_plan_items_status",
        ),
        CheckConstraint(
            "estimated_seconds BETWEEN 1 AND 3600",
            name="ck_daily_plan_items_estimated_seconds",
        ),
        CheckConstraint("position >= 0", name="ck_daily_plan_items_position"),
        Index("ix_daily_plan_items_plan_id", "plan_id"),
        Index("ix_daily_plan_items_enrollment_id", "enrollment_id"),
        Index("ix_daily_plan_items_card_id", "card_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("daily_plans.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    item_type: Mapped[str] = mapped_column(String(16), nullable=False)
    enrollment_id: Mapped[int] = mapped_column(
        ForeignKey("card_enrollments.id", ondelete="RESTRICT"), nullable=False
    )
    card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="RESTRICT"), nullable=False
    )
    estimated_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_detail: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default="pending", index=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())

    plan: Mapped[DailyPlan] = relationship(back_populates="items")
    enrollment: Mapped[CardEnrollment] = relationship("CardEnrollment")
    card: Mapped[Card] = relationship("Card")
