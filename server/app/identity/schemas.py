from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Any, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

ProfileScore = Annotated[int, Field(ge=1, le=5)]


class GoalType(StrEnum):
    DAILY_LEARNING = "daily_learning"
    EXAM = "exam"
    FOCUSED = "focused"


class OwnerCreate(BaseModel):
    display_name: str | None = Field(default=None, max_length=64)
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=64)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        normalized = value.strip()
        try:
            ZoneInfo(normalized)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("timezone must be a valid IANA timezone name") from exc
        return normalized


class LearningProfileValues(BaseModel):
    goal_type: GoalType = GoalType.DAILY_LEARNING
    target_date: date | None = None
    daily_minutes: int = Field(default=20, ge=5, le=240)
    study_days: list[bool] = Field(default_factory=lambda: [True] * 7, min_length=7, max_length=7)
    desired_retention: float = Field(default=0.90, ge=0.70, le=0.99)
    new_card_ceiling: int = Field(default=5, ge=0, le=100)
    subject_priorities: dict[str, ProfileScore] = Field(default_factory=dict)
    initial_self_assessment: dict[str, ProfileScore] = Field(default_factory=dict)

    @field_validator("subject_priorities", "initial_self_assessment")
    @classmethod
    def normalize_subject_scores(cls, value: dict[str, int]) -> dict[str, int]:
        if len(value) > 64:
            raise ValueError("subject score maps support at most 64 entries")
        normalized: dict[str, int] = {}
        for raw_key, score in value.items():
            key = raw_key.strip()
            if not key:
                raise ValueError("subject names must not be empty")
            if len(key) > 64:
                raise ValueError("subject names must not exceed 64 characters")
            if key in normalized:
                raise ValueError("subject names must be unique after trimming")
            normalized[key] = score
        return normalized

    @model_validator(mode="after")
    def require_study_day(self) -> LearningProfileValues:
        if not any(self.study_days):
            raise ValueError("at least one study day must be enabled")
        return self


class LearningProfileUpdate(BaseModel):
    """Partial update contract for PUT /me/learning-profile.

    Only provided fields are applied. `expected_updated_at` is required for concurrency.
    Owner fields (`display_name`, `timezone`) may be updated alongside profile fields.
    """

    expected_updated_at: datetime
    goal_type: GoalType | None = None
    target_date: date | None = None
    daily_minutes: int | None = Field(default=None, ge=5, le=240)
    study_days: list[bool] | None = Field(default=None, min_length=7, max_length=7)
    desired_retention: float | None = Field(default=None, ge=0.70, le=0.99)
    new_card_ceiling: int | None = Field(default=None, ge=0, le=100)
    subject_priorities: dict[str, ProfileScore] | None = None
    initial_self_assessment: dict[str, ProfileScore] | None = None
    onboarding_completed: bool | None = None
    display_name: str | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("expected_updated_at")
    @classmethod
    def require_timezone_aware_updated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("expected_updated_at must include a timezone")
        return value

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        try:
            ZoneInfo(normalized)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("timezone must be a valid IANA timezone name") from exc
        return normalized

    @field_validator("subject_priorities", "initial_self_assessment")
    @classmethod
    def normalize_subject_scores(cls, value: dict[str, int] | None) -> dict[str, int] | None:
        if value is None:
            return None
        if len(value) > 64:
            raise ValueError("subject score maps support at most 64 entries")
        normalized: dict[str, int] = {}
        for raw_key, score in value.items():
            key = raw_key.strip()
            if not key:
                raise ValueError("subject names must not be empty")
            if len(key) > 64:
                raise ValueError("subject names must not exceed 64 characters")
            if key in normalized:
                raise ValueError("subject names must be unique after trimming")
            normalized[key] = score
        return normalized

    @model_validator(mode="after")
    def require_study_day_when_provided(self) -> Self:
        if self.study_days is not None and not any(self.study_days):
            raise ValueError("at least one study day must be enabled")
        return self

    def provided_fields(self) -> set[str]:
        # expected_updated_at is concurrency metadata, not a profile field.
        return {name for name in self.model_fields_set if name != "expected_updated_at"}


class LearningProfileOut(BaseModel):
    id: int
    user_id: int
    goal_type: GoalType
    target_date: date | None
    daily_minutes: int
    study_days: list[bool]
    desired_retention: float
    new_card_ceiling: int
    subject_priorities: dict[str, int]
    initial_self_assessment: dict[str, int]
    onboarding_completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    display_name: str | None = None
    timezone: str

    @classmethod
    def from_entities(cls, profile: Any, owner: Any) -> LearningProfileOut:
        return cls(
            id=profile.id,
            user_id=profile.user_id,
            goal_type=GoalType(profile.goal_type),
            target_date=profile.target_date,
            daily_minutes=profile.daily_minutes,
            study_days=list(profile.study_days),
            desired_retention=profile.desired_retention,
            new_card_ceiling=profile.new_card_ceiling,
            subject_priorities=dict(profile.subject_priorities or {}),
            initial_self_assessment=dict(profile.initial_self_assessment or {}),
            onboarding_completed_at=profile.onboarding_completed_at,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
            display_name=owner.display_name,
            timezone=owner.timezone,
        )
