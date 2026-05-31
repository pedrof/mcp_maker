"""CRUD/query MCP tool generators and handlers.

Per-model isolation is the hard invariant here: every instance access goes through
_load_instance(model_id, instance_id, db) which enforces three predicates:
  id = :instance_id  AND  model_id = :model_id  AND  deleted_at IS NULL.
Direct `db.get(Instance, id)` is NEVER used — it would allow cross-model reads.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import mcp.types as types
from app.models.instance import Instance
from app.models.model import ForgeModel
from mcp.shared.exceptions import McpError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# ── Tool definitions ────────────────────────────────────────────────────────


def crud_tool_defs(model: ForgeModel) -> list[types.Tool]:
    return [
        types.Tool(
            name="create_instance",
            description=(
                f"Create a new instance of the '{model.name}' model. "
                "The data is validated against the model schema before being stored."
            ),
            inputSchema=model.json_schema,
        ),
        types.Tool(
            name="get_instance",
            description=f"Retrieve a live instance of '{model.name}' by its ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "instance_id": {"type": "string", "description": "UUID of the instance"}
                },
                "required": ["instance_id"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="update_instance",
            description=(
                f"Replace the data of an existing '{model.name}' instance. "
                "New data is validated against the model schema."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "instance_id": {"type": "string", "description": "UUID of the instance"},
                    "data": {
                        **model.json_schema,
                        "description": "New data — must conform to the model schema",
                    },
                },
                "required": ["instance_id", "data"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="delete_instance",
            description=(
                f"Soft-delete an instance of '{model.name}'. "
                "The record is retained but excluded from all future reads."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "instance_id": {"type": "string", "description": "UUID of the instance"}
                },
                "required": ["instance_id"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="list_instances",
            description=(
                f"List live (non-deleted) instances of '{model.name}', newest first."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max results (1–100, default 20)",
                        "minimum": 1,
                        "maximum": 100,
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Pagination offset (default 0)",
                        "minimum": 0,
                    },
                },
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="query_instances",
            description=(
                f"Filter and paginate live instances of '{model.name}'. "
                "Filters are equality matches on top-level data fields. "
                "Values are compared as text; numeric equality works for whole numbers."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "filters": {
                        "type": "object",
                        "description": (
                            "Key/value pairs to match against top-level fields in data. "
                            'e.g. {"division": "Alpha"}'
                        ),
                        "additionalProperties": {"type": "string"},
                    },
                    "sort_by": {
                        "type": "string",
                        "description": "Top-level data field name to sort by (text order)",
                    },
                    "sort_order": {
                        "type": "string",
                        "enum": ["asc", "desc"],
                        "description": "Sort direction (default: asc)",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "description": "Max results (default 20)",
                    },
                    "offset": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "Pagination offset (default 0)",
                    },
                },
                "additionalProperties": False,
            },
        ),
    ]


# ── Internal helper — the isolation guard ────────────────────────────────────


async def _load_instance(
    model_id: str, instance_id: str, db: AsyncSession
) -> Instance:
    """Load an alive instance scoped to model_id.

    Enforces three predicates: id, model_id, and deleted_at IS NULL.
    Never skips any of them — cross-model access must be impossible.
    """
    stmt = select(Instance).where(
        Instance.id == instance_id,
        Instance.model_id == model_id,
        Instance.deleted_at.is_(None),
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise McpError(
            types.ErrorData(
                code=types.INVALID_PARAMS,
                message=f"Instance '{instance_id}' not found for model '{model_id}'",
            )
        )
    return row


def _instance_to_dict(inst: Instance) -> dict[str, Any]:
    return {
        "id": inst.id,
        "model_id": inst.model_id,
        "data": inst.data,
        "created_at": inst.created_at.isoformat() if inst.created_at else None,
        "updated_at": inst.updated_at.isoformat() if inst.updated_at else None,
    }


# ── Validation helper ────────────────────────────────────────────────────────


def _schema_errors(data: Any, schema: dict[str, Any]) -> list[str]:
    import jsonschema

    try:
        jsonschema.validate(data, schema)
        return []
    except jsonschema.ValidationError as e:
        return [e.message]
    except jsonschema.SchemaError as e:
        raise McpError(
            types.ErrorData(code=types.INTERNAL_ERROR, message=f"Invalid schema: {e.message}")
        ) from e


# ── Tool handlers ────────────────────────────────────────────────────────────


async def create_instance(
    arguments: dict[str, Any], model: ForgeModel, db: AsyncSession
) -> list[types.TextContent]:
    errors = _schema_errors(arguments, model.json_schema)
    if errors:
        return [
            types.TextContent(
                type="text",
                text=json.dumps({"created": False, "errors": errors}),
            )
        ]
    now = datetime.now(UTC)
    instance = Instance(
        id=str(uuid.uuid4()),
        model_id=model.id,
        data=arguments,
        created_at=now,
        updated_at=now,
    )
    db.add(instance)
    await db.commit()
    await db.refresh(instance)
    return [
        types.TextContent(
            type="text",
            text=json.dumps({"created": True, **_instance_to_dict(instance)}),
        )
    ]


async def get_instance(
    arguments: dict[str, Any], model: ForgeModel, db: AsyncSession
) -> list[types.TextContent]:
    instance_id = arguments.get("instance_id", "")
    instance = await _load_instance(model.id, instance_id, db)
    return [types.TextContent(type="text", text=json.dumps(_instance_to_dict(instance)))]


async def update_instance(
    arguments: dict[str, Any], model: ForgeModel, db: AsyncSession
) -> list[types.TextContent]:
    instance_id = arguments.get("instance_id", "")
    new_data = arguments.get("data")
    if new_data is None:
        raise McpError(
            types.ErrorData(code=types.INVALID_PARAMS, message="'data' argument is required")
        )
    errors = _schema_errors(new_data, model.json_schema)
    if errors:
        return [
            types.TextContent(
                type="text",
                text=json.dumps({"updated": False, "errors": errors}),
            )
        ]
    instance = await _load_instance(model.id, instance_id, db)
    instance.data = new_data
    instance.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(instance)
    return [
        types.TextContent(
            type="text",
            text=json.dumps({"updated": True, **_instance_to_dict(instance)}),
        )
    ]


async def delete_instance(
    arguments: dict[str, Any], model: ForgeModel, db: AsyncSession
) -> list[types.TextContent]:
    instance_id = arguments.get("instance_id", "")
    instance = await _load_instance(model.id, instance_id, db)
    instance.deleted_at = datetime.now(UTC)
    await db.commit()
    return [
        types.TextContent(
            type="text",
            text=json.dumps({"deleted": True, "id": instance.id}),
        )
    ]


async def list_instances(
    arguments: dict[str, Any], model: ForgeModel, db: AsyncSession
) -> list[types.TextContent]:
    limit = min(int(arguments.get("limit", 20)), 100)
    offset = max(int(arguments.get("offset", 0)), 0)

    base = select(Instance).where(
        Instance.model_id == model.id,
        Instance.deleted_at.is_(None),
    )
    count_stmt = select(func.count()).select_from(base.subquery())
    total: int = (await db.execute(count_stmt)).scalar_one()

    rows_stmt = (
        base.order_by(Instance.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(rows_stmt)).scalars().all()
    return [
        types.TextContent(
            type="text",
            text=json.dumps(
                {
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                    "instances": [_instance_to_dict(r) for r in rows],
                }
            ),
        )
    ]


async def query_instances(
    arguments: dict[str, Any], model: ForgeModel, db: AsyncSession
) -> list[types.TextContent]:
    filters: dict[str, str] = arguments.get("filters") or {}
    sort_by: str | None = arguments.get("sort_by")
    sort_order: str = arguments.get("sort_order", "asc")
    limit = min(int(arguments.get("limit", 20)), 100)
    offset = max(int(arguments.get("offset", 0)), 0)

    base = select(Instance).where(
        Instance.model_id == model.id,
        Instance.deleted_at.is_(None),
    )
    for field, value in filters.items():
        # Text-equality on JSONB field. data->>'field' = 'value'
        base = base.where(
            func.jsonb_extract_path_text(Instance.data, field) == str(value)
        )

    count_stmt = select(func.count()).select_from(base.subquery())
    total: int = (await db.execute(count_stmt)).scalar_one()

    if sort_by:
        col = func.jsonb_extract_path_text(Instance.data, sort_by)
        order_col = col.desc() if sort_order == "desc" else col.asc()
        base = base.order_by(order_col)
    else:
        base = base.order_by(Instance.created_at.desc())

    rows = (await db.execute(base.limit(limit).offset(offset))).scalars().all()
    return [
        types.TextContent(
            type="text",
            text=json.dumps(
                {
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                    "instances": [_instance_to_dict(r) for r in rows],
                }
            ),
        )
    ]
