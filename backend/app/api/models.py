"""REST API for model authoring: CRUD on drafts + publish/unpublish lifecycle."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

import jsonschema
import jsonschema.exceptions
from app.api.deps import DbDep, OwnerDep
from app.models.model import ForgeModel, ModelStatus, ModelVersion, Visibility
from app.schemas.models import (
    ModelCreate,
    ModelRead,
    ModelUpdate,
    PublishResponse,
)
from fastapi import APIRouter, HTTPException
from sqlalchemy import select

router = APIRouter(prefix="/api/models", tags=["models"])

# ── Helpers ─────────────────────────────────────────────────────────────────


def _slugify(name: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", name.lower())
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return slug[:128] or "model"


async def _unique_slug(base: str, db: Any) -> str:
    """Return base slug if unused, else base-{uuid4 suffix}."""
    existing = await db.get(ForgeModel, base)
    if existing is None:
        return base
    return f"{base[:100]}-{uuid.uuid4().hex[:8]}"


def _validate_json_schema(schema: dict[str, Any]) -> None:
    """Validate that schema is a valid JSON Schema. Raises HTTPException on failure."""
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.exceptions.SchemaError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"json_schema is not a valid JSON Schema: {exc.message}",
        ) from exc


def _model_to_read(model: ForgeModel) -> ModelRead:
    return ModelRead(
        id=model.id,
        name=model.name,
        description=model.description,
        json_schema=model.json_schema,
        system_prompt=model.system_prompt,
        enabled_tool_classes=list(model.enabled_tool_classes),
        metrics_config=dict(model.metrics_config),
        visibility=model.visibility.value,
        status=model.status.value,
        current_version=model.current_version,
        owner_sub=model.owner_sub,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


# ── CRUD ─────────────────────────────────────────────────────────────────────


@router.post("", response_model=ModelRead, status_code=201)
async def create_model(
    body: ModelCreate, db: DbDep, owner: OwnerDep
) -> ModelRead:
    model_id = body.id or await _unique_slug(_slugify(body.name), db)
    if await db.get(ForgeModel, model_id):
        raise HTTPException(status_code=409, detail=f"Model id '{model_id}' already exists")

    now = datetime.now(UTC)
    model = ForgeModel(
        id=model_id,
        name=body.name,
        description=body.description,
        json_schema=body.json_schema,
        system_prompt=body.system_prompt,
        enabled_tool_classes=body.enabled_tool_classes,
        metrics_config=body.metrics_config,
        visibility=Visibility(body.visibility),
        owner_sub=owner,
        status=ModelStatus.draft,
        current_version=0,
        created_at=now,
        updated_at=now,
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return _model_to_read(model)


@router.get("", response_model=list[ModelRead])
async def list_models(db: DbDep, owner: OwnerDep) -> list[ModelRead]:
    stmt = (
        select(ForgeModel)
        .where(ForgeModel.owner_sub == owner)
        .order_by(ForgeModel.created_at.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [_model_to_read(r) for r in rows]


@router.get("/{model_id}", response_model=ModelRead)
async def get_model(model_id: str, db: DbDep, owner: OwnerDep) -> ModelRead:
    model = await db.get(ForgeModel, model_id)
    if model is None or model.owner_sub != owner:
        raise HTTPException(status_code=404, detail="Model not found")
    return _model_to_read(model)


@router.patch("/{model_id}", response_model=ModelRead)
async def update_model(
    model_id: str, body: ModelUpdate, db: DbDep, owner: OwnerDep
) -> ModelRead:
    model = await db.get(ForgeModel, model_id)
    if model is None or model.owner_sub != owner:
        raise HTTPException(status_code=404, detail="Model not found")
    if model.status == ModelStatus.published:
        raise HTTPException(
            status_code=409,
            detail="Cannot edit a published model. Unpublish it first.",
        )

    if body.name is not None:
        model.name = body.name
    if body.description is not None:
        model.description = body.description
    if body.json_schema is not None:
        model.json_schema = body.json_schema
    if body.system_prompt is not None:
        model.system_prompt = body.system_prompt
    if body.enabled_tool_classes is not None:
        model.enabled_tool_classes = body.enabled_tool_classes
    if body.metrics_config is not None:
        model.metrics_config = body.metrics_config
    if body.visibility is not None:
        model.visibility = Visibility(body.visibility)

    model.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(model)
    return _model_to_read(model)


# ── Lifecycle ─────────────────────────────────────────────────────────────────


@router.post("/{model_id}/publish", response_model=PublishResponse)
async def publish_model(
    model_id: str, db: DbDep, owner: OwnerDep
) -> PublishResponse:
    model = await db.get(ForgeModel, model_id)
    if model is None or model.owner_sub != owner:
        raise HTTPException(status_code=404, detail="Model not found")
    if model.status == ModelStatus.published:
        raise HTTPException(status_code=409, detail="Model is already published")

    # Validate schema before freezing
    if not model.json_schema:
        raise HTTPException(
            status_code=422,
            detail="json_schema must be non-empty before publishing",
        )
    _validate_json_schema(model.json_schema)

    # Bump version and snapshot current config — all in one transaction
    new_version = model.current_version + 1
    version_row = ModelVersion(
        id=str(uuid.uuid4()),
        model_id=model.id,
        version_number=new_version,
        json_schema=dict(model.json_schema),
        system_prompt=model.system_prompt,
        enabled_tool_classes=list(model.enabled_tool_classes),
        metrics_config=dict(model.metrics_config),
    )
    db.add(version_row)

    model.current_version = new_version
    model.status = ModelStatus.published
    model.updated_at = datetime.now(UTC)
    await db.commit()

    return PublishResponse(
        model_id=model.id,
        version=new_version,
        status="published",
        mcp_endpoint=f"/mcp/{model.id}",
    )


@router.post("/{model_id}/unpublish", response_model=ModelRead)
async def unpublish_model(
    model_id: str, db: DbDep, owner: OwnerDep
) -> ModelRead:
    model = await db.get(ForgeModel, model_id)
    if model is None or model.owner_sub != owner:
        raise HTTPException(status_code=404, detail="Model not found")
    if model.status != ModelStatus.published:
        raise HTTPException(
            status_code=409,
            detail=f"Model is not published (status: {model.status.value})",
        )

    model.status = ModelStatus.unpublished
    model.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(model)
    return _model_to_read(model)
