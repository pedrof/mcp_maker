"""Pydantic v2 request/response schemas for the Models API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ModelCreate(BaseModel):
    id: str | None = Field(
        default=None,
        description="Optional slug id; auto-generated from name if omitted",
    )
    name: str = Field(min_length=1, max_length=256)
    description: str | None = None
    json_schema: dict[str, Any] = Field(default_factory=dict)
    system_prompt: str | None = None
    enabled_tool_classes: list[str] = Field(default_factory=list)
    metrics_config: dict[str, Any] = Field(default_factory=dict)
    visibility: str = "public"

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, v: str) -> str:
        if v not in ("public", "protected"):
            raise ValueError("visibility must be 'public' or 'protected'")
        return v

    @field_validator("enabled_tool_classes")
    @classmethod
    def validate_tool_classes(cls, v: list[str]) -> list[str]:
        valid = {"schema_only", "crud", "scenario"}
        for tc in v:
            if tc not in valid:
                raise ValueError(f"Unknown tool class: {tc!r}. Valid: {sorted(valid)}")
        return v


class ModelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = None
    json_schema: dict[str, Any] | None = None
    system_prompt: str | None = None
    enabled_tool_classes: list[str] | None = None
    metrics_config: dict[str, Any] | None = None
    visibility: str | None = None

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, v: str | None) -> str | None:
        if v is not None and v not in ("public", "protected"):
            raise ValueError("visibility must be 'public' or 'protected'")
        return v

    @field_validator("enabled_tool_classes")
    @classmethod
    def validate_tool_classes(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        valid = {"schema_only", "crud", "scenario"}
        for tc in v:
            if tc not in valid:
                raise ValueError(f"Unknown tool class: {tc!r}")
        return v


class ModelRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    name: str
    description: str | None
    json_schema: dict[str, Any]
    system_prompt: str | None
    enabled_tool_classes: list[str]
    metrics_config: dict[str, Any]
    visibility: str
    status: str
    current_version: int
    owner_sub: str
    created_at: datetime
    updated_at: datetime


class VersionRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    model_id: str
    version_number: int
    json_schema: dict[str, Any]
    system_prompt: str | None
    enabled_tool_classes: list[str]
    metrics_config: dict[str, Any]
    created_at: datetime


class PublishResponse(BaseModel):
    model_id: str
    version: int
    status: str
    mcp_endpoint: str
