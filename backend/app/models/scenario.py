from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.db import Base
from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.models.model import ForgeModel


class Scenario(Base):  # type: ignore[misc]
    __tablename__ = "scenarios"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    model_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("models.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    # Copy of live instances at create_scenario time: [{id, data}, ...]
    base_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    # Accumulated changes: [{op, instance_id?, data?}, ...]
    changes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    # "active" | "done"
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    # Cached output of the last compute_metrics call
    computed_results: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    model: Mapped[ForgeModel] = relationship("ForgeModel")
