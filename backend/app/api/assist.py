"""POST /api/assist/system-prompt — AI-assisted system prompt authoring."""

from __future__ import annotations

import json
import re
from typing import Annotated, Any

from anthropic import AsyncAnthropic
from app.api.deps import DbDep, OwnerDep
from app.clients.anthropic_client import get_anthropic_client
from app.config import settings
from app.mcp.gateway import _build_tool_defs
from app.models.model import ForgeModel
from app.schemas.assist import AssistRequest, AssistResponse
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(prefix="/api/assist", tags=["assist"])

AnthropicDep = Annotated[AsyncAnthropic, Depends(get_anthropic_client)]

_ASSIST_SYSTEM = """\
You are an expert system prompt author for Model Context Protocol (MCP) servers.
Given a JSON Schema data model, the available tools, and the user's stated intent,
produce a robust system prompt that:
  1. Explains the data model to the downstream LLM in plain language.
  2. Describes when and how to use each available tool.
  3. Sets sensible guardrails (e.g. validate before writing, soft-delete only).
  4. Is parameterizable where useful (e.g. {focus_area} placeholder).

Always respond with ONLY valid JSON — no markdown, no prose outside the JSON:
{"system_prompt": "...", "rationale": "..."}
"""


def _tool_summary(tools: list[Any]) -> str:
    lines = []
    for t in tools:
        desc = getattr(t, "description", "") or ""
        lines.append(f"- {t.name}: {desc[:120]}")
    return "\n".join(lines) or "(no tools enabled)"


def _parse_assist_json(raw: str) -> tuple[str, str]:
    """Extract system_prompt and rationale from Claude's response.

    Tolerant: tries direct parse, then code-block extraction, then regex.
    """
    # Strip markdown code fences if present
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip()
    try:
        data = json.loads(cleaned)
        return str(data["system_prompt"]), str(data.get("rationale", ""))
    except (json.JSONDecodeError, KeyError):
        pass
    # Regex fallback
    sp = re.search(r'"system_prompt"\s*:\s*"(.*?)"(?=\s*[,}])', raw, re.DOTALL)
    rt = re.search(r'"rationale"\s*:\s*"(.*?)"(?=\s*[,}])', raw, re.DOTALL)
    return (
        sp.group(1).replace("\\n", "\n") if sp else raw,
        rt.group(1).replace("\\n", "\n") if rt else "",
    )


@router.post("/system-prompt", response_model=AssistResponse)
async def assist_system_prompt(
    body: AssistRequest,
    db: DbDep,
    owner: OwnerDep,
    client: AnthropicDep,
) -> AssistResponse:
    """Draft or refine a system prompt grounded in the model's schema and tools."""
    model = await db.get(ForgeModel, body.model_id)
    if model is None or model.owner_sub != owner:
        raise HTTPException(status_code=404, detail="Model not found")

    tool_summary = _tool_summary(_build_tool_defs(model))
    schema_str = json.dumps(model.json_schema, indent=2)

    if body.prior_draft and body.feedback:
        # Refine turn: include prior draft + user feedback
        user_content = (
            f"Schema:\n```json\n{schema_str}\n```\n\n"
            f"Available tools:\n{tool_summary}\n\n"
            f"Use-case: {body.intent}\n\n"
            f"Prior draft:\n{body.prior_draft}\n\n"
            f"User feedback: {body.feedback}\n\n"
            "Please refine the system prompt based on the feedback."
        )
    else:
        # First draft
        user_content = (
            f"Schema:\n```json\n{schema_str}\n```\n\n"
            f"Available tools:\n{tool_summary}\n\n"
            f"Use-case: {body.intent}\n\n"
            "Write the system prompt."
        )

    response = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=2048,
        system=_ASSIST_SYSTEM,
        messages=[{"role": "user", "content": user_content}],
    )
    text_blocks = [b for b in response.content if b.type == "text"]
    raw = text_blocks[0].text if text_blocks else "{}"
    system_prompt, rationale = _parse_assist_json(raw)

    return AssistResponse(
        model_id=body.model_id,
        system_prompt=system_prompt,
        rationale=rationale,
    )
