"""Schema-only MCP tool generators and handlers."""

from __future__ import annotations

import json
from typing import Any

import mcp.types as types
from app.models.model import ForgeModel
from mcp.shared.exceptions import McpError


def schema_only_tool_defs(model: ForgeModel) -> list[types.Tool]:
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
                    "data": {"type": "object", "description": "The JSON object to validate"}
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


def call_schema_only_tool(
    name: str, arguments: dict[str, Any], model: ForgeModel
) -> list[types.TextContent]:
    if name == "get_schema":
        return [types.TextContent(type="text", text=json.dumps(model.json_schema, indent=2))]
    if name == "describe_model":
        return [
            types.TextContent(
                type="text",
                text=json.dumps(
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
                ),
            )
        ]
    if name == "validate_instance":
        return _validate(arguments, model)
    if name == "generate_example":
        return [
            types.TextContent(
                type="text",
                text=json.dumps(_schema_to_example(model.json_schema), indent=2),
            )
        ]
    raise McpError(
        types.ErrorData(code=types.METHOD_NOT_FOUND, message=f"Unknown schema-only tool: {name}")
    )


def _validate(
    arguments: dict[str, Any], model: ForgeModel
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


def _schema_to_example(schema: dict[str, Any]) -> Any:
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
        return {k: _schema_to_example(v) for k, v in props.items() if k in required}
    if t == "array" or (isinstance(t, list) and "array" in t):
        return [_schema_to_example(schema.get("items", {"type": "string"}))]
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
