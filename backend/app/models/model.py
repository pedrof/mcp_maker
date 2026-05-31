from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from app.db import Base
from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship


class ModelStatus(str, enum.Enum):
    draft = "draft"
    published = "published"
    unpublished = "unpublished"


class Visibility(str, enum.Enum):
    public = "public"
    protected = "protected"


class ToolClass(str, enum.Enum):
    crud = "crud"
    scenario = "scenario"
    schema_only = "schema_only"


class ForgeModel(Base):  # type: ignore[misc]
    __tablename__ = "models"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    json_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Array of ToolClass values stored as JSONB
    enabled_tool_classes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # Derived/aggregate metric definitions for the scenario engine
    metrics_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    visibility: Mapped[Visibility] = mapped_column(
        Enum(Visibility, name="visibility_enum"), nullable=False, default=Visibility.public
    )
    # bcrypt hash of the bearer API key; NULL when visibility=public
    api_key_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    owner_sub: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[ModelStatus] = mapped_column(
        Enum(ModelStatus, name="model_status_enum"), nullable=False, default=ModelStatus.draft
    )
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    versions: Mapped[list[ModelVersion]] = relationship(
        "ModelVersion", back_populates="model", cascade="all, delete-orphan"
    )
    instances: Mapped[list[Instance]] = relationship(  # noqa: F821
        "Instance", back_populates="model", cascade="all, delete-orphan"
    )


class ModelVersion(Base):  # type: ignore[misc]
    __tablename__ = "model_versions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    model_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("models.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    json_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled_tool_classes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    metrics_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    model: Mapped[ForgeModel] = relationship("ForgeModel", back_populates="versions")


# Avoid circular at type-check time; Instance is in instance.py
from app.models.instance import Instance  # noqa: E402, F401
