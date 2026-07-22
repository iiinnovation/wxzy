from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import LearningProfile, User
from .schemas import LearningProfileValues, OwnerCreate


class ActiveOwnerExistsError(RuntimeError):
    pass


class LearningProfileNotFoundError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(UTC)


def require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime values must include a timezone")
    return value.astimezone(UTC)


def build_default_learning_profile(user_id: int, *, now: datetime | None = None) -> LearningProfile:
    timestamp = require_aware_utc(now or utc_now())
    values = LearningProfileValues()
    return LearningProfile(
        user_id=user_id,
        goal_type=values.goal_type.value,
        target_date=values.target_date,
        daily_minutes=values.daily_minutes,
        study_days=list(values.study_days),
        desired_retention=values.desired_retention,
        new_card_ceiling=values.new_card_ceiling,
        subject_priorities=dict(values.subject_priorities),
        initial_self_assessment=dict(values.initial_self_assessment),
        created_at=timestamp,
        updated_at=timestamp,
    )


def create_owner_with_default_profile(
    db: Session, data: OwnerCreate, *, now: datetime | None = None
) -> User:
    timestamp = require_aware_utc(now or utc_now())
    owner = User(
        status="active",
        display_name=data.display_name,
        timezone=data.timezone,
        created_at=timestamp,
        updated_at=timestamp,
    )
    db.add(owner)
    try:
        db.flush()
        owner.learning_profile = build_default_learning_profile(owner.id, now=timestamp)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        active_owner_id = db.scalar(select(User.id).where(User.status == "active").limit(1))
        if active_owner_id is not None:
            raise ActiveOwnerExistsError("an active Owner already exists") from exc
        raise
    db.refresh(owner)
    return owner


def update_learning_profile(
    db: Session,
    *,
    user_id: int,
    values: LearningProfileValues,
    now: datetime | None = None,
) -> LearningProfile:
    profile = db.scalar(select(LearningProfile).where(LearningProfile.user_id == user_id).limit(1))
    if profile is None:
        raise LearningProfileNotFoundError(f"learning profile for user {user_id} was not found")

    profile.goal_type = values.goal_type.value
    profile.target_date = values.target_date
    profile.daily_minutes = values.daily_minutes
    profile.study_days = list(values.study_days)
    profile.desired_retention = values.desired_retention
    profile.new_card_ceiling = values.new_card_ceiling
    profile.subject_priorities = dict(values.subject_priorities)
    profile.initial_self_assessment = dict(values.initial_self_assessment)
    profile.updated_at = require_aware_utc(now or utc_now())
    db.commit()
    db.refresh(profile)
    return profile
