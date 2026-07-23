from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class WeChatLoginIn(BaseModel):
    code: str = Field(min_length=1, max_length=512)
    device_label: str | None = Field(default=None, max_length=128)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("code must not be blank")
        return normalized

    @field_validator("device_label")
    @classmethod
    def normalize_device_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class OwnerOut(BaseModel):
    id: int
    status: str
    display_name: str | None
    timezone: str


class SessionTokenOut(BaseModel):
    access_token: str = Field(min_length=32, repr=False)
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    owner: OwnerOut
