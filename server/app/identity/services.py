from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import LearningProfile, LearningProfileAudit, User
from .schemas import GoalType, LearningProfileUpdate, LearningProfileValues, OwnerCreate


class ActiveOwnerExistsError(RuntimeError):
    pass


class LearningProfileNotFoundError(RuntimeError):
    pass


class LearningProfileConflictError(RuntimeError):
    """Raised when expected_updated_at does not match the stored profile."""

    def __init__(self, current_updated_at: datetime) -> None:
        super().__init__("learning profile was modified by another request")
        self.current_updated_at = current_updated_at


PROFILE_AUDIT_FIELDS = (
    "goal_type",
    "target_date",
    "daily_minutes",
    "study_days",
    "desired_retention",
    "new_card_ceiling",
    "subject_priorities",
    "initial_self_assessment",
    "onboarding_completed_at",
    "display_name",
    "timezone",
)


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


def get_learning_profile(db: Session, *, user_id: int) -> LearningProfile:
    profile = db.scalar(select(LearningProfile).where(LearningProfile.user_id == user_id).limit(1))
    if profile is None:
        raise LearningProfileNotFoundError(f"learning profile for user {user_id} was not found")
    return profile


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return require_aware_utc(value).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, GoalType):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _profile_snapshot(profile: LearningProfile, owner: User) -> dict[str, Any]:
    return {
        "goal_type": profile.goal_type,
        "target_date": _json_safe(profile.target_date),
        "daily_minutes": profile.daily_minutes,
        "study_days": list(profile.study_days),
        "desired_retention": profile.desired_retention,
        "new_card_ceiling": profile.new_card_ceiling,
        "subject_priorities": dict(profile.subject_priorities or {}),
        "initial_self_assessment": dict(profile.initial_self_assessment or {}),
        "onboarding_completed_at": _json_safe(profile.onboarding_completed_at),
        "display_name": owner.display_name,
        "timezone": owner.timezone,
    }


def _timestamps_match(left: datetime, right: datetime) -> bool:
    return require_aware_utc(left) == require_aware_utc(right)


def update_learning_profile(
    db: Session,
    *,
    user_id: int,
    values: LearningProfileValues,
    now: datetime | None = None,
) -> LearningProfile:
    profile = get_learning_profile(db, user_id=user_id)
    owner = db.get(User, user_id)
    if owner is None:
        raise LearningProfileNotFoundError(f"learning profile for user {user_id} was not found")

    before = _profile_snapshot(profile, owner)
    profile.goal_type = values.goal_type.value
    profile.target_date = values.target_date
    profile.daily_minutes = values.daily_minutes
    profile.study_days = list(values.study_days)
    profile.desired_retention = values.desired_retention
    profile.new_card_ceiling = values.new_card_ceiling
    profile.subject_priorities = dict(values.subject_priorities)
    profile.initial_self_assessment = dict(values.initial_self_assessment)
    timestamp = require_aware_utc(now or utc_now())
    profile.updated_at = timestamp
    after = _profile_snapshot(profile, owner)
    changed = [field for field in PROFILE_AUDIT_FIELDS if before.get(field) != after.get(field)]
    if changed:
        db.add(
            LearningProfileAudit(
                user_id=user_id,
                profile_id=profile.id,
                changed_fields=changed,
                before_values={field: before[field] for field in changed},
                after_values={field: after[field] for field in changed},
                created_at=timestamp,
            )
        )
    db.commit()
    db.refresh(profile)
    return profile


def apply_learning_profile_update(
    db: Session,
    *,
    owner: User,
    update: LearningProfileUpdate,
    now: datetime | None = None,
) -> LearningProfile:
    profile = get_learning_profile(db, user_id=owner.id)
    if not _timestamps_match(profile.updated_at, update.expected_updated_at):
        raise LearningProfileConflictError(current_updated_at=profile.updated_at)

    provided = update.provided_fields()
    if not provided:
        return profile

    before = _profile_snapshot(profile, owner)
    timestamp = require_aware_utc(now or utc_now())

    if "goal_type" in provided and update.goal_type is not None:
        profile.goal_type = update.goal_type.value
    if "target_date" in provided:
        profile.target_date = update.target_date
    if "daily_minutes" in provided and update.daily_minutes is not None:
        profile.daily_minutes = update.daily_minutes
    if "study_days" in provided and update.study_days is not None:
        profile.study_days = list(update.study_days)
    if "desired_retention" in provided and update.desired_retention is not None:
        profile.desired_retention = update.desired_retention
    if "new_card_ceiling" in provided and update.new_card_ceiling is not None:
        profile.new_card_ceiling = update.new_card_ceiling
    if "subject_priorities" in provided and update.subject_priorities is not None:
        profile.subject_priorities = dict(update.subject_priorities)
    if "initial_self_assessment" in provided and update.initial_self_assessment is not None:
        profile.initial_self_assessment = dict(update.initial_self_assessment)
    if "onboarding_completed" in provided and update.onboarding_completed is not None:
        if update.onboarding_completed:
            if profile.onboarding_completed_at is None:
                profile.onboarding_completed_at = timestamp
        else:
            profile.onboarding_completed_at = None
    if "display_name" in provided:
        owner.display_name = update.display_name
        owner.updated_at = timestamp
    if "timezone" in provided and update.timezone is not None:
        owner.timezone = update.timezone
        owner.updated_at = timestamp

    profile.updated_at = timestamp
    after = _profile_snapshot(profile, owner)
    changed = [field for field in PROFILE_AUDIT_FIELDS if before.get(field) != after.get(field)]
    if changed:
        db.add(
            LearningProfileAudit(
                user_id=owner.id,
                profile_id=profile.id,
                changed_fields=changed,
                before_values={field: before[field] for field in changed},
                after_values={field: after[field] for field in changed},
                created_at=timestamp,
            )
        )
    db.commit()
    db.refresh(profile)
    db.refresh(owner)
    return profile
