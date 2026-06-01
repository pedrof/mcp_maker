"""Pydantic v2 schemas for /api/assist and /api/test endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ── Assist / system-prompt ───────────────────────────────────────────────────


class AssistRequest(BaseModel):
    model_id: str
    intent: str = Field(min_length=1, description="User's stated use-case for the model")
    # Refine-turn fields — both must be provided together for a refine call
    prior_draft: str | None = Field(
        default=None,
        description="System prompt draft from a previous assist call",
    )
    feedback: str | None = Field(
        default=None,
        description="User feedback on the prior draft to guide the refinement",
    )


class AssistResponse(BaseModel):
    model_id: str
    system_prompt: str
    rationale: str


# ── Test session ─────────────────────────────────────────────────────────────


class SessionMessage(BaseModel):
    role: str = Field(description="'user' or 'assistant'")
    content: str


class TestSessionRequest(BaseModel):
    model_id: str
    messages: list[SessionMessage] = Field(min_length=1)


class TestSessionResponse(BaseModel):
    model_id: str
    response: str
    tool_calls_made: int
    messages: list[dict[str, Any]]  # Full Anthropic message history for multi-turn
