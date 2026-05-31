"""Scenario / what-if MCP tool generators and handlers.

Design decisions (see ADR-003):
  - Snapshot-copy: at create_scenario, live instance data is copied into base_snapshot.
    All subsequent ops run only on that copy + changes. Live instances are never touched.
  - Declarative metrics only: metrics_config = {name: {agg, field}}
    Supported agg functions: count, sum, avg, min, max.
    No eval(), no expression language.
  - _load_scenario enforces model_id isolation (same pattern as _load_instance in crud.py).
"""

from __future__ import annotations

import copy
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import mcp.types as types
from app.models.instance import Instance
from app.models.model import ForgeModel
from app.models.scenario import Scenario
from mcp.shared.exceptions import McpError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ── Tool definitions ────────────────────────────────────────────────────────


def scenario_tool_defs(model: ForgeModel) -> list[types.Tool]:
    return [
        types.Tool(
            name="create_scenario",
            description=(
                f"Create a what-if scenario for '{model.name}'. "
                "Snapshots the current live instances and evaluates baseline metrics. "
                "Returns the scenario_id and baseline metric values."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Human-readable scenario name"}
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="apply_change",
            description=(
                "Apply a sandboxed change to a scenario's working set. "
                "Ops: 'add' (new synthetic instance), 'update' (replace instance data), "
                "'remove' (exclude instance from working set). "
                "Live data is NEVER modified."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "scenario_id": {"type": "string"},
                    "op": {
                        "type": "string",
                        "enum": ["add", "update", "remove"],
                        "description": "Change operation",
                    },
                    "instance_id": {
                        "type": "string",
                        "description": "Required for 'update' and 'remove'. "
                        "Must be an id present in the baseline snapshot.",
                    },
                    "data": {
                        "type": "object",
                        "description": "Required for 'add' and 'update'. "
                        "Must conform to the model schema.",
                    },
                },
                "required": ["scenario_id", "op"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="compute_metrics",
            description=(
                "Evaluate the model's metrics_config against the scenario's current working "
                "set (baseline + applied changes). Caches the result on the scenario. "
                "Returns a dict of metric_name → value."
            ),
            inputSchema={
                "type": "object",
                "properties": {"scenario_id": {"type": "string"}},
                "required": ["scenario_id"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="compare_to_baseline",
            description=(
                "Compare the scenario's current metric values against the baseline "
                "(snapshot-only, no changes). Returns per-metric deltas."
            ),
            inputSchema={
                "type": "object",
                "properties": {"scenario_id": {"type": "string"}},
                "required": ["scenario_id"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="reset_scenario",
            description=(
                "Discard all applied changes and cached metrics, returning the "
                "scenario to its original baseline state."
            ),
            inputSchema={
                "type": "object",
                "properties": {"scenario_id": {"type": "string"}},
                "required": ["scenario_id"],
                "additionalProperties": False,
            },
        ),
    ]


# ── Isolation guard ──────────────────────────────────────────────────────────


async def _load_scenario(
    model_id: str, scenario_id: str, db: AsyncSession
) -> Scenario:
    """Load a scenario scoped to model_id — prevents cross-tenant access."""
    stmt = select(Scenario).where(
        Scenario.id == scenario_id,
        Scenario.model_id == model_id,
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise McpError(
            types.ErrorData(
                code=types.INVALID_PARAMS,
                message=f"Scenario '{scenario_id}' not found for model '{model_id}'",
            )
        )
    return row


# ── Working-set helpers ──────────────────────────────────────────────────────


def _apply_changes_to_snapshot(
    base_snapshot: list[dict[str, Any]],
    changes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return a new list representing snapshot + all changes applied in order.

    Each snapshot item: {"id": str, "data": dict}
    Each change item:   {"op": "add"|"update"|"remove", "instance_id"?: str, "data"?: dict}
    """
    working: list[dict[str, Any]] = copy.deepcopy(base_snapshot)
    for change in changes:
        op = change.get("op")
        if op == "add":
            working.append(
                {"id": change.get("synthetic_id", str(uuid.uuid4())), "data": change["data"]}
            )
        elif op == "update":
            iid = change.get("instance_id")
            for item in working:
                if item["id"] == iid:
                    item["data"] = copy.deepcopy(change["data"])
                    break
        elif op == "remove":
            iid = change.get("instance_id")
            working = [item for item in working if item["id"] != iid]
    return working


# ── Metrics computation ──────────────────────────────────────────────────────


def _compute_metrics_for_working_set(
    working_set: list[dict[str, Any]],
    metrics_config: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate declarative aggregates over the working set.

    metrics_config format: {metric_name: {"agg": "count|sum|avg|min|max", "field"?: str}}
    Returns None for a metric when the field is absent in all items or the set is empty.
    """
    results: dict[str, Any] = {}
    for metric_name, metric_def in metrics_config.items():
        agg = metric_def.get("agg")
        field = metric_def.get("field")

        if agg == "count":
            results[metric_name] = len(working_set)
            continue

        # All other aggs require a field
        if not field:
            results[metric_name] = None
            continue

        numeric_values = [
            v
            for item in working_set
            if isinstance((v := item["data"].get(field)), int | float)
        ]

        if not numeric_values:
            results[metric_name] = None
        elif agg == "sum":
            results[metric_name] = sum(numeric_values)
        elif agg == "avg":
            results[metric_name] = sum(numeric_values) / len(numeric_values)
        elif agg == "min":
            results[metric_name] = min(numeric_values)
        elif agg == "max":
            results[metric_name] = max(numeric_values)
        else:
            results[metric_name] = None

    return results


# ── Tool handlers ────────────────────────────────────────────────────────────


async def create_scenario(
    arguments: dict[str, Any], model: ForgeModel, db: AsyncSession
) -> list[types.TextContent]:
    name = arguments.get("name", "")
    if not name:
        raise McpError(
            types.ErrorData(code=types.INVALID_PARAMS, message="'name' is required")
        )

    # Snapshot live (non-deleted) instances for this model
    stmt = select(Instance).where(
        Instance.model_id == model.id,
        Instance.deleted_at.is_(None),
    )
    live_rows = (await db.execute(stmt)).scalars().all()
    snapshot = [{"id": r.id, "data": r.data} for r in live_rows]

    # Compute baseline metrics from the snapshot (no changes yet)
    baseline_metrics = _compute_metrics_for_working_set(snapshot, model.metrics_config)

    now = datetime.now(UTC)
    scenario = Scenario(
        id=str(uuid.uuid4()),
        model_id=model.id,
        name=name,
        base_snapshot=snapshot,
        changes=[],
        status="active",
        computed_results={"baseline": baseline_metrics},
        created_at=now,
        updated_at=now,
    )
    db.add(scenario)
    await db.commit()
    await db.refresh(scenario)
    return [
        types.TextContent(
            type="text",
            text=json.dumps(
                {
                    "scenario_id": scenario.id,
                    "name": scenario.name,
                    "snapshot_size": len(snapshot),
                    "baseline_metrics": baseline_metrics,
                }
            ),
        )
    ]


async def apply_change(
    arguments: dict[str, Any], model: ForgeModel, db: AsyncSession
) -> list[types.TextContent]:
    scenario_id = arguments.get("scenario_id", "")
    op = arguments.get("op", "")
    instance_id = arguments.get("instance_id")
    data = arguments.get("data")

    if op not in ("add", "update", "remove"):
        raise McpError(
            types.ErrorData(
                code=types.INVALID_PARAMS,
                message="'op' must be one of: add, update, remove",
            )
        )
    if op in ("update", "remove") and not instance_id:
        raise McpError(
            types.ErrorData(
                code=types.INVALID_PARAMS,
                message=f"'instance_id' is required for op='{op}'",
            )
        )
    if op in ("add", "update") and data is None:
        raise McpError(
            types.ErrorData(
                code=types.INVALID_PARAMS,
                message=f"'data' is required for op='{op}'",
            )
        )

    scenario = await _load_scenario(model.id, scenario_id, db)
    change: dict[str, Any] = {"op": op}
    if instance_id:
        change["instance_id"] = instance_id
    if data is not None:
        change["data"] = data
    if op == "add":
        change["synthetic_id"] = str(uuid.uuid4())

    # Append change (do not touch live data)
    updated_changes = list(scenario.changes) + [change]
    scenario.changes = updated_changes
    scenario.updated_at = datetime.now(UTC)
    await db.commit()
    return [
        types.TextContent(
            type="text",
            text=json.dumps(
                {
                    "applied": True,
                    "scenario_id": scenario_id,
                    "op": op,
                    "total_changes": len(updated_changes),
                }
            ),
        )
    ]


async def compute_metrics(
    arguments: dict[str, Any], model: ForgeModel, db: AsyncSession
) -> list[types.TextContent]:
    scenario_id = arguments.get("scenario_id", "")
    scenario = await _load_scenario(model.id, scenario_id, db)
    working_set = _apply_changes_to_snapshot(scenario.base_snapshot, scenario.changes)
    current_metrics = _compute_metrics_for_working_set(working_set, model.metrics_config)

    # Cache results
    updated_results = dict(scenario.computed_results)
    updated_results["current"] = current_metrics
    scenario.computed_results = updated_results
    scenario.status = "done"
    scenario.updated_at = datetime.now(UTC)
    await db.commit()
    return [
        types.TextContent(
            type="text",
            text=json.dumps(
                {
                    "scenario_id": scenario_id,
                    "working_set_size": len(working_set),
                    "metrics": current_metrics,
                }
            ),
        )
    ]


async def compare_to_baseline(
    arguments: dict[str, Any], model: ForgeModel, db: AsyncSession
) -> list[types.TextContent]:
    scenario_id = arguments.get("scenario_id", "")
    scenario = await _load_scenario(model.id, scenario_id, db)

    baseline_metrics = _compute_metrics_for_working_set(
        scenario.base_snapshot, model.metrics_config
    )
    working_set = _apply_changes_to_snapshot(scenario.base_snapshot, scenario.changes)
    current_metrics = _compute_metrics_for_working_set(working_set, model.metrics_config)

    comparison: dict[str, Any] = {}
    all_metrics = set(baseline_metrics) | set(current_metrics)
    for metric in all_metrics:
        base_val = baseline_metrics.get(metric)
        curr_val = current_metrics.get(metric)
        delta: float | None = None
        if isinstance(base_val, int | float) and isinstance(curr_val, int | float):
            delta = curr_val - base_val
        comparison[metric] = {"baseline": base_val, "current": curr_val, "delta": delta}

    return [
        types.TextContent(
            type="text",
            text=json.dumps(
                {
                    "scenario_id": scenario_id,
                    "comparison": comparison,
                }
            ),
        )
    ]


async def reset_scenario(
    arguments: dict[str, Any], model: ForgeModel, db: AsyncSession
) -> list[types.TextContent]:
    scenario_id = arguments.get("scenario_id", "")
    scenario = await _load_scenario(model.id, scenario_id, db)
    baseline_metrics = _compute_metrics_for_working_set(
        scenario.base_snapshot, model.metrics_config
    )
    scenario.changes = []
    scenario.computed_results = {"baseline": baseline_metrics}
    scenario.status = "active"
    scenario.updated_at = datetime.now(UTC)
    await db.commit()
    return [
        types.TextContent(
            type="text",
            text=json.dumps(
                {
                    "reset": True,
                    "scenario_id": scenario_id,
                    "snapshot_size": len(scenario.base_snapshot),
                    "baseline_metrics": baseline_metrics,
                }
            ),
        )
    ]
