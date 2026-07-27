from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

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


class MobileActivateIn(BaseModel):
    activation_code: str = Field(min_length=1, max_length=256, repr=False)
    device_label: str | None = Field(default=None, max_length=128)

    @field_validator("activation_code")
    @classmethod
    def normalize_activation_code(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("activation_code must not be blank")
        return normalized

    @field_validator("device_label")
    @classmethod
    def normalize_mobile_device_label(cls, value: str | None) -> str | None:
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


class SessionDeviceOut(BaseModel):
    id: int
    device_label: str | None
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    status: Literal["active", "expired", "revoked"]
    current: bool


class SessionDeviceListOut(BaseModel):
    items: list[SessionDeviceOut]


class OwnerDataExportOut(BaseModel):
    schema_version: Literal["wxzy-owner-export-v1"] = "wxzy-owner-export-v1"
    generated_at: datetime
    backup_status: Literal["not_configured"] = "not_configured"
    owner: OwnerOut
    learning_profile: dict[str, Any]
    sessions: list[SessionDeviceOut]
    learning_data: dict[str, list[dict[str, Any]]]


class AccountDeleteIn(BaseModel):
    confirmation: Literal["DELETE_MY_DATA"]
