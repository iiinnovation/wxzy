from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated
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
