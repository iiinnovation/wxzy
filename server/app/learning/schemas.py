from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class EnrollmentStatus(StrEnum):
    QUEUED = "queued"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    RETIRED = "retired"


class EnrollmentSource(StrEnum):
    MANUAL = "manual"
    CHAPTER = "chapter"
    PLAN = "plan"


class EnrollmentCreate(BaseModel):
    user_id: int = Field(gt=0)
    card_id: int = Field(gt=0)
    priority: int = Field(default=50, ge=0, le=100)
    source: EnrollmentSource = EnrollmentSource.MANUAL
