"""POST /api/test/session — ephemeral MCP session against a draft model.

Reuses the gateway's dispatch_tool_call so draft models get the same tool
implementations as published ones, without any code duplication.

Security: owner-scoped via OwnerDep; loads model by id+owner, bypasses the
published-only gate intentionally — the point is to test *before* publishing.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any

from anthropic import AsyncAnthropic
from app.api.deps import DbDep, OwnerDep
from app.clients.anthropic_client import get_anthropic_client
from app.config import settings
from app.db import AsyncSessionLocal
from app.mcp.gateway import _build_tool_defs, dispatch_tool_call
from app.models.model import ForgeModel
from app.schemas.assist import TestSessionRequest, TestSessionResponse
from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/test", tags=["test-session"])

AnthropicDep = Annotated[AsyncAnthropic, Depends(get_anthropic_client)]

_MAX_TOOL_ITERATIONS = 8


def _mcp_tools_to_anthropic(model: ForgeModel) -> list[dict[str, Any]]:
    """Convert MCP Tool objects to Anthropic tool dicts.

    MCP uses camelCase inputSchema; Anthropic API requires snake_case input_schema.
    """
    result = []
    for tool in _build_tool_defs(model):
        result.append(
            {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.inputSchema,
            }
        )
    return result


@router.post("/session", response_model=TestSessionResponse)
async def test_session(
    body: TestSessionRequest,
    db: DbDep,
    owner: OwnerDep,
    client: AnthropicDep,
) -> TestSessionResponse:
    """Run an ephemeral Claude session against a draft (or any-status) model.

    The session loop:
    1. Send user messages + model tools to Claude.
    2. If Claude calls a tool, dispatch it through the same gateway logic as
       the published MCP endpoint, append the result, call Claude again.
    3. Repeat up to _MAX_TOOL_ITERATIONS times, then return the final text.
    """
    model = await db.get(ForgeModel, body.model_id)
    if model is None or model.owner_sub != owner:
        raise HTTPException(status_code=404, detail="Model not found")

    anthropic_tools = _mcp_tools_to_anthropic(model)
    messages: list[dict[str, Any]] = [
        {"role": m.role, "content": m.content} for m in body.messages
    ]

    tool_calls_made = 0
    final_text = ""

    for _ in range(_MAX_TOOL_ITERATIONS):
        kwargs: dict[str, Any] = {
            "model": settings.anthropic_model,
            "max_tokens": 4096,
            "messages": messages,
        }
        if model.system_prompt:
            kwargs["system"] = model.system_prompt
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools

        response = await client.messages.create(**kwargs)

        # Collect text content for the final answer
        text_blocks = [b.text for b in response.content if b.type == "text"]
        final_text = "\n".join(text_blocks)

        if response.stop_reason != "tool_use":
            break

        # Process all tool_use blocks in this response
        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
        if not tool_use_blocks:
            break

        # Append assistant turn (contains tool_use blocks)
        messages.append({"role": "assistant", "content": response.content})

        # Execute tools and build the tool_result user turn
        tool_results: list[dict[str, Any]] = []
        for block in tool_use_blocks:
            tool_calls_made += 1
            try:
                async with AsyncSessionLocal() as tool_db:
                    content_items = await dispatch_tool_call(
                        block.name,
                        dict(block.input) if block.input else {},
                        model,
                        tool_db,
                    )
                result_text = (
                    content_items[0].text if content_items else ""
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Tool %s failed: %s", block.name, exc)
                result_text = json.dumps({"error": str(exc)})

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                }
            )

        messages.append({"role": "user", "content": tool_results})

    return TestSessionResponse(
        model_id=body.model_id,
        response=final_text,
        tool_calls_made=tool_calls_made,
        messages=messages,
    )
