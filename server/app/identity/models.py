from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.types import UTCDateTime
from ..db import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'disabled')", name="ck_users_status"),
        UniqueConstraint("wechat_openid_hash", name="uq_users_wechat_openid_hash"),
        Index(
            "uq_users_single_active_owner",
            "status",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wechat_openid_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    display_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timezone: Mapped[str] = mapped_column(
        String(64), default="Asia/Shanghai", server_default="Asia/Shanghai"
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now()
    )

    sessions: Mapped[list[UserSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    learning_profile: Mapped[LearningProfile | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )


class UserSession(Base):
    __tablename__ = "user_sessions"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_user_sessions_token_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    device_label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="sessions")


class LearningProfile(Base):
    __tablename__ = "learning_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_learning_profiles_user_id"),
        CheckConstraint(
            "goal_type IN ('daily_learning', 'exam', 'focused')",
            name="ck_learning_profiles_goal_type",
        ),
        CheckConstraint(
            "daily_minutes BETWEEN 5 AND 240", name="ck_learning_profiles_daily_minutes"
        ),
        CheckConstraint(
            "desired_retention BETWEEN 0.70 AND 0.99",
            name="ck_learning_profiles_desired_retention",
        ),
        CheckConstraint(
            "new_card_ceiling BETWEEN 0 AND 100",
            name="ck_learning_profiles_new_card_ceiling",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    goal_type: Mapped[str] = mapped_column(
        String(32), default="daily_learning", server_default="daily_learning"
    )
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    daily_minutes: Mapped[int] = mapped_column(Integer, default=20, server_default="20")
    study_days: Mapped[list[bool]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=lambda: [True] * 7,
        server_default=text("'[true,true,true,true,true,true,true]'"),
    )
    desired_retention: Mapped[float] = mapped_column(Float, default=0.90, server_default="0.90")
    new_card_ceiling: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    subject_priorities: Mapped[dict[str, int]] = mapped_column(
        MutableDict.as_mutable(JSON), default=dict, server_default=text("'{}'")
    )
    initial_self_assessment: Mapped[dict[str, int]] = mapped_column(
        MutableDict.as_mutable(JSON), default=dict, server_default=text("'{}'")
    )
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="learning_profile")


class LearningProfileAudit(Base):
    """Append-only snapshot of learning-profile field changes."""

    __tablename__ = "learning_profile_audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("learning_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    changed_fields: Mapped[list[str]] = mapped_column(MutableList.as_mutable(JSON), nullable=False)
    before_values: Mapped[dict[str, object]] = mapped_column(
        MutableDict.as_mutable(JSON), nullable=False
    )
    after_values: Mapped[dict[str, object]] = mapped_column(
        MutableDict.as_mutable(JSON), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
