"""
Dynamic multi-tenant MCP gateway.

One Server + one StreamableHTTPSessionManager serve N published models.
Per-request model resolution: server.request_context.request.path_params["model_id"]
→ Starlette Request built from ASGI scope which FastAPI populates with path params.
See docs/mcp-notes.md for transport + stateless details.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.db import AsyncSessionLocal
from app.models.model import ForgeModel, ModelStatus
from pydantic import AnyUrl
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


# ── Schema-only tool definitions ─────────────────────────────────────────────


def _schema_only_tools(model: ForgeModel) -> list[types.Tool]:
    return [
        types.Tool(
            name="get_schema",
            description=(
                f"Return the JSON Schema (Draft 2020-12) for the '{model.name}' model. "
                "Use this to understand what fields and types are valid for instances."
            ),
            inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        types.Tool(
            name="describe_model",
            description=(
                f"Return metadata about the '{model.name}' model: name, description, "
                "enabled capabilities, and current version."
            ),
            inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        types.Tool(
            name="validate_instance",
            description=(
                f"Validate a JSON object against the '{model.name}' schema. "
                "Returns validation errors if the object does not conform."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "data": {
                        "type": "object",
                        "description": "The JSON object to validate",
                    }
                },
                "required": ["data"],
                "additionalProperties": False,
            },
        ),
        types.Tool(
            name="generate_example",
            description=(
                f"Generate a schema-faithful example instance for the '{model.name}' model. "
                "Useful for understanding expected data shape before creating real instances."
            ),
            inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
    ]


# ── Tool call implementations ────────────────────────────────────────────────


def _tool_get_schema(model: ForgeModel) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=json.dumps(model.json_schema, indent=2))]


def _tool_describe_model(model: ForgeModel) -> list[types.TextContent]:
    description = {
        "id": model.id,
        "name": model.name,
        "description": model.description,
        "version": model.current_version,
        "enabled_tool_classes": model.enabled_tool_classes,
        "visibility": model.visibility.value,
        "status": model.status.value,
    }
    return [types.TextContent(type="text", text=json.dumps(description, indent=2))]


def _tool_validate_instance(
    model: ForgeModel, arguments: dict[str, Any]
) -> list[types.TextContent]:
    import jsonschema

    data = arguments.get("data")
    if data is None:
        raise McpError(
            types.ErrorData(code=types.INVALID_PARAMS, message="'data' argument is required")
        )
    try:
        jsonschema.validate(data, model.json_schema)
        return [types.TextContent(type="text", text=json.dumps({"valid": True, "errors": []}))]
    except jsonschema.ValidationError as e:
        return [
            types.TextContent(
                type="text",
                text=json.dumps({"valid": False, "errors": [e.message]}),
            )
        ]
    except jsonschema.SchemaError as e:
        raise McpError(
            types.ErrorData(code=types.INTERNAL_ERROR, message=f"Invalid schema: {e.message}")
        ) from e


def _tool_generate_example(model: ForgeModel) -> list[types.TextContent]:
    """Generate a minimal schema-faithful example by walking the JSON Schema."""
    example = _schema_to_example(model.json_schema)
    return [types.TextContent(type="text", text=json.dumps(example, indent=2))]


def _schema_to_example(schema: dict[str, Any]) -> Any:
    """Recursively build a minimal example value from a JSON Schema node."""
    if "examples" in schema and schema["examples"]:
        return schema["examples"][0]
    if "default" in schema:
        return schema["default"]
    if "const" in schema:
        return schema["const"]
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]

    t = schema.get("type")
    if t == "object" or (isinstance(t, list) and "object" in t):
        props = schema.get("properties", {})
        required = set(schema.get("required", props.keys()))
        return {
            k: _schema_to_example(v)
            for k, v in props.items()
            if k in required
        }
    if t == "array" or (isinstance(t, list) and "array" in t):
        items = schema.get("items", {"type": "string"})
        return [_schema_to_example(items)]
    if t == "string":
        return schema.get("title", "example")
    if t == "integer":
        return schema.get("minimum", 0)
    if t == "number":
        return schema.get("minimum", 0.0)
    if t == "boolean":
        return True
    if t == "null":
        return None
    return {}


# ── MCP handler registration ─────────────────────────────────────────────────


@server.list_tools()  # type: ignore[misc, no-untyped-call]
async def handle_list_tools() -> list[types.Tool]:
    model_id = _current_model_id()
    model = await _load_published_model(model_id)
    return _schema_only_tools(model)


@server.call_tool()  # type: ignore[misc]
async def handle_call_tool(
    name: str, arguments: dict[str, Any] | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    model_id = _current_model_id()
    model = await _load_published_model(model_id)
    args = arguments or {}

    if name == "get_schema":
        return _tool_get_schema(model)  # type: ignore[return-value]
    if name == "describe_model":
        return _tool_describe_model(model)  # type: ignore[return-value]
    if name == "validate_instance":
        return _tool_validate_instance(model, args)  # type: ignore[return-value]
    if name == "generate_example":
        return _tool_generate_example(model)  # type: ignore[return-value]

    raise McpError(
        types.ErrorData(code=types.METHOD_NOT_FOUND, message=f"Unknown tool: {name}")
    )


@server.list_resources()  # type: ignore[misc, no-untyped-call]
async def handle_list_resources() -> list[types.Resource]:
    model_id = _current_model_id()
    model = await _load_published_model(model_id)
    return [
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
