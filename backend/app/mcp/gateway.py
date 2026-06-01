"""
Dynamic multi-tenant MCP gateway.

One Server + one StreamableHTTPSessionManager serve N published models.
Per-request model resolution: server.request_context.request.path_params["model_id"]
→ Starlette Request built from ASGI scope which FastAPI populates with path params.
See docs/decisions/ADR-002 and docs/mcp-notes.md.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.db import AsyncSessionLocal
from app.models.model import ForgeModel, ModelStatus
from app.tools import crud as crud_tools
from app.tools import scenario as scenario_tools
from app.tools import schema_only as so_tools
from pydantic import AnyUrl
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

import mcp.types as types
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.shared.exceptions import McpError

logger = logging.getLogger(__name__)

# Single shared Server + manager for all models (never re-created after lifespan starts)
server: Server[None, Request] = Server(
    name="forge-gateway",
    version="0.1.0",
    instructions=(
        "FORGE dynamic MCP gateway. "
        "Use list_tools, list_resources, and list_prompts to discover this model's capabilities."
    ),
)

session_manager = StreamableHTTPSessionManager(
    app=server,
    json_response=True,
    stateless=True,
)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _current_model_id() -> str:
    """Read model_id from the current request's path params via the SDK's request_ctx."""
    req = server.request_context.request
    if not isinstance(req, Request):
        raise McpError(
            types.ErrorData(code=types.INTERNAL_ERROR, message="No HTTP request in context")
        )
    model_id: str = req.path_params["model_id"]
    return model_id


async def _load_published_model(model_id: str) -> ForgeModel:
    """Fetch a published model from Postgres. Raises McpError if not found/published."""
    async with AsyncSessionLocal() as db:
        model = await db.get(ForgeModel, model_id)
    if model is None or model.status != ModelStatus.published:
        raise McpError(
            types.ErrorData(
                code=types.INVALID_PARAMS,
                message=f"Model '{model_id}' not found or not published",
            )
        )
    return model


def _build_tool_defs(model: ForgeModel) -> list[types.Tool]:
    """Union tool definitions for all enabled tool classes."""
    classes = set(model.enabled_tool_classes)
    tools: list[types.Tool] = []
    if "schema_only" in classes:
        tools.extend(so_tools.schema_only_tool_defs(model))
    if "crud" in classes:
        tools.extend(crud_tools.crud_tool_defs(model))
    if "scenario" in classes:
        tools.extend(scenario_tools.scenario_tool_defs(model))
    return tools


_SCHEMA_ONLY_NAMES = {"get_schema", "describe_model", "validate_instance", "generate_example"}
_CRUD_NAMES = {
    "create_instance",
    "get_instance",
    "update_instance",
    "delete_instance",
    "list_instances",
    "query_instances",
}
_SCENARIO_NAMES = {
    "create_scenario",
    "apply_change",
    "compute_metrics",
    "compare_to_baseline",
    "reset_scenario",
}


# ── Shared tool dispatcher (reused by gateway handlers and test-session API) ─


async def dispatch_tool_call(
    name: str,
    args: dict[str, Any],
    model: ForgeModel,
    db: AsyncSession,
) -> Any:
    """Execute a named tool against a model (any status) with a provided db session.

    Called by:
    - handle_call_tool (published models via the MCP gateway)
    - /api/test/session (draft/unpublished models via the authoring API)
    """
    classes = set(model.enabled_tool_classes)

    if name in _SCHEMA_ONLY_NAMES:
        if "schema_only" not in classes:
            raise McpError(
                types.ErrorData(
                    code=types.METHOD_NOT_FOUND,
                    message=f"Tool '{name}' not enabled for model '{model.id}'",
                )
            )
        return so_tools.call_schema_only_tool(name, args, model)

    if name in _CRUD_NAMES:
        if "crud" not in classes:
            raise McpError(
                types.ErrorData(
                    code=types.METHOD_NOT_FOUND,
                    message=f"Tool '{name}' not enabled for model '{model.id}'",
                )
            )
        if name == "create_instance":
            return await crud_tools.create_instance(args, model, db)
        if name == "get_instance":
            return await crud_tools.get_instance(args, model, db)
        if name == "update_instance":
            return await crud_tools.update_instance(args, model, db)
        if name == "delete_instance":
            return await crud_tools.delete_instance(args, model, db)
        if name == "list_instances":
            return await crud_tools.list_instances(args, model, db)
        return await crud_tools.query_instances(args, model, db)

    if name in _SCENARIO_NAMES:
        if "scenario" not in classes:
            raise McpError(
                types.ErrorData(
                    code=types.METHOD_NOT_FOUND,
                    message=f"Tool '{name}' not enabled for model '{model.id}'",
                )
            )
        if name == "create_scenario":
            return await scenario_tools.create_scenario(args, model, db)
        if name == "apply_change":
            return await scenario_tools.apply_change(args, model, db)
        if name == "compute_metrics":
            return await scenario_tools.compute_metrics(args, model, db)
        if name == "compare_to_baseline":
            return await scenario_tools.compare_to_baseline(args, model, db)
        return await scenario_tools.reset_scenario(args, model, db)

    raise McpError(
        types.ErrorData(code=types.METHOD_NOT_FOUND, message=f"Unknown tool: {name}")
    )


# ── MCP handler registration ─────────────────────────────────────────────────


@server.list_tools()  # type: ignore[misc, no-untyped-call]
async def handle_list_tools() -> list[types.Tool]:
    model_id = _current_model_id()
    model = await _load_published_model(model_id)
    return _build_tool_defs(model)


@server.call_tool(validate_input=False)  # type: ignore[misc]
async def handle_call_tool(
    name: str, arguments: dict[str, Any] | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    model_id = _current_model_id()
    model = await _load_published_model(model_id)
    args = arguments or {}
    async with AsyncSessionLocal() as db:
        return await dispatch_tool_call(name, args, model, db)  # type: ignore[no-any-return]


@server.list_resources()  # type: ignore[misc, no-untyped-call]
async def handle_list_resources() -> list[types.Resource]:
    model_id = _current_model_id()
    model = await _load_published_model(model_id)
    resources = [
        types.Resource(
            uri=f"schema://{model_id}",  # type: ignore[arg-type]
            name=f"{model.name} — JSON Schema",
            description="The JSON Schema (Draft 2020-12) defining this model's data shape",
            mimeType="application/schema+json",
        ),
        types.Resource(
            uri=f"model://{model_id}",  # type: ignore[arg-type]
            name=f"{model.name} — Model metadata",
            description="Name, description, capabilities, and version of this model",
            mimeType="application/json",
        ),
    ]
    return resources


@server.read_resource()  # type: ignore[misc, no-untyped-call]
async def handle_read_resource(uri: AnyUrl) -> str:
    uri_str = str(uri)
    if uri_str.startswith("schema://"):
        model_id = uri_str.removeprefix("schema://")
        model = await _load_published_model(model_id)
        return json.dumps(model.json_schema, indent=2)
    if uri_str.startswith("model://"):
        model_id = uri_str.removeprefix("model://")
        model = await _load_published_model(model_id)
        return json.dumps(
            {
                "id": model.id,
                "name": model.name,
                "description": model.description,
                "version": model.current_version,
                "enabled_tool_classes": model.enabled_tool_classes,
                "visibility": model.visibility.value,
                "status": model.status.value,
            },
            indent=2,
        )
    raise McpError(
        types.ErrorData(code=types.INVALID_PARAMS, message=f"Unknown resource URI: {uri_str}")
    )


@server.list_prompts()  # type: ignore[misc, no-untyped-call]
async def handle_list_prompts() -> list[types.Prompt]:
    model_id = _current_model_id()
    model = await _load_published_model(model_id)
    if not model.system_prompt:
        return []
    return [
        types.Prompt(
            name="strategize",
            description=(
                f"System prompt for the '{model.name}' model. "
                "Grounds the LLM in the data model and explains available tools."
            ),
            arguments=[
                types.PromptArgument(
                    name="focus",
                    description="Optional focus area to emphasize in the strategy session",
                    required=False,
                )
            ],
        )
    ]


@server.get_prompt()  # type: ignore[misc, no-untyped-call]
async def handle_get_prompt(
    name: str, arguments: dict[str, str] | None
) -> types.GetPromptResult:
    if name != "strategize":
        raise McpError(
            types.ErrorData(code=types.INVALID_PARAMS, message=f"Unknown prompt: {name}")
        )
    model_id = _current_model_id()
    model = await _load_published_model(model_id)
    if not model.system_prompt:
        raise McpError(
            types.ErrorData(
                code=types.INVALID_PARAMS,
                message=f"Model '{model_id}' has no system prompt configured",
            )
        )
    focus = (arguments or {}).get("focus", "")
    content = model.system_prompt
    if focus:
        content = f"{content}\n\nFocus for this session: {focus}"
    return types.GetPromptResult(
        description=f"System prompt for {model.name}",
        messages=[
            types.PromptMessage(
                role="user",
                content=types.TextContent(type="text", text=content),
            )
        ],
    )
