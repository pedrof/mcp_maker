"""
Phase 6 assist + test-session integration tests.

Uses a strict fake AsyncAnthropic client injected via app.dependency_overrides.
The fake asserts on the shape of what it receives (not just that it was called),
turning it into a contract-checker for the Anthropic message format.

Real API calls are skipped unless ANTHROPIC_API_KEY is set (live-test guard).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

# NOTE: app.* imports are deferred to function bodies — importing them at module
# level would trigger app.config.Settings() during pytest collection, before the
# testcontainer sets DATABASE_URL, giving every test the wrong DB URL.
# See conftest.py feedback notes.

# ── Fake Anthropic client helpers ─────────────────────────────────────────────


def _text_response(text: str, stop_reason: str = "end_turn") -> MagicMock:
    """Build a fake Anthropic message response returning a single text block."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    resp.stop_reason = stop_reason
    return resp


def _tool_use_then_text(
    tool_name: str,
    tool_input: dict[str, Any],
    tool_use_id: str,
    final_text: str,
) -> list[MagicMock]:
    """Return two sequential fake responses: tool_use then text."""
    # First response: Claude calls a tool
    tu_block = MagicMock()
    tu_block.type = "tool_use"
    tu_block.id = tool_use_id
    tu_block.name = tool_name
    tu_block.input = tool_input

    first = MagicMock()
    first.content = [tu_block]
    first.stop_reason = "tool_use"

    # Second response: Claude returns text
    second = _text_response(final_text)
    return [first, second]


class _StrictFakeClient:
    """Fake AsyncAnthropic whose messages.create is an AsyncMock.

    'strict' means it records every call's arguments for assertion.
    """

    def __init__(self, responses: list[MagicMock]) -> None:
        self._responses = iter(responses)
        self.calls: list[dict[str, Any]] = []

        async def _create(**kwargs: Any) -> MagicMock:
            self.calls.append(kwargs)
            return next(self._responses)

        self.messages = MagicMock()
        self.messages.create = AsyncMock(side_effect=_create)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def _schema_only_model_id() -> str:
    """model-alpha is schema_only — good for test-session without side effects."""
    return "model-alpha"


# ── Assist tests ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_assist_returns_prompt_and_rationale(live_server: AsyncClient) -> None:
    fake_response = json.dumps(
        {
            "system_prompt": "You manage org readiness data...",
            "rationale": "Grounded in the schema fields.",
        }
    )
    fake = _StrictFakeClient([_text_response(fake_response)])

    from app.clients.anthropic_client import get_anthropic_client
    from app.main import app

    app.dependency_overrides[get_anthropic_client] = lambda: fake
    try:
        resp = await live_server.post(
            "/api/assist/system-prompt",
            json={
                "model_id": "model-alpha",
                "intent": "Help users reason about division readiness",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "system_prompt" in body
        assert len(body["system_prompt"]) > 10
        assert "rationale" in body

        # Assert the schema and intent actually appeared in the message sent to Claude
        assert fake.calls, "Expected Claude to be called"
        call_messages = fake.calls[0]["messages"]
        first_user = call_messages[0]["content"]
        assert "org readiness" in first_user.lower() or "division" in first_user.lower()
        assert "division readiness" in first_user.lower()
    finally:
        app.dependency_overrides.pop(get_anthropic_client, None)


@pytest.mark.asyncio
async def test_assist_refine_turn_includes_feedback(live_server: AsyncClient) -> None:
    """A refine call must include the prior draft and feedback in the message sent to Claude."""
    fake_response = json.dumps(
        {"system_prompt": "Refined prompt...", "rationale": "Adjusted per feedback."}
    )
    fake = _StrictFakeClient([_text_response(fake_response)])

    from app.clients.anthropic_client import get_anthropic_client
    from app.main import app

    app.dependency_overrides[get_anthropic_client] = lambda: fake
    try:
        resp = await live_server.post(
            "/api/assist/system-prompt",
            json={
                "model_id": "model-alpha",
                "intent": "Readiness analysis",
                "prior_draft": "You are a helpful assistant.",
                "feedback": "Make it more specific about the personnel_pct field.",
            },
        )
        assert resp.status_code == 200

        # The feedback text must have reached the client
        call_content = fake.calls[0]["messages"][0]["content"]
        assert "personnel_pct" in call_content
        assert "Make it more specific" in call_content
    finally:
        app.dependency_overrides.pop(get_anthropic_client, None)


@pytest.mark.asyncio
async def test_assist_model_not_found_returns_404(live_server: AsyncClient) -> None:
    fake = _StrictFakeClient([])
    from app.clients.anthropic_client import get_anthropic_client
    from app.main import app

    app.dependency_overrides[get_anthropic_client] = lambda: fake
    try:
        resp = await live_server.post(
            "/api/assist/system-prompt",
            json={"model_id": "nonexistent-xyz", "intent": "anything"},
        )
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_anthropic_client, None)


# ── Test-session tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_session_simple_text_response(live_server: AsyncClient) -> None:
    fake = _StrictFakeClient([_text_response("The schema has a division field.")])
    from app.clients.anthropic_client import get_anthropic_client
    from app.main import app

    app.dependency_overrides[get_anthropic_client] = lambda: fake
    try:
        resp = await live_server.post(
            "/api/test/session",
            json={
                "model_id": "model-alpha",
                "messages": [{"role": "user", "content": "Describe this model."}],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "division" in body["response"].lower() or len(body["response"]) > 0
        assert body["tool_calls_made"] == 0
    finally:
        app.dependency_overrides.pop(get_anthropic_client, None)


@pytest.mark.asyncio
async def test_session_tool_use_loop(live_server: AsyncClient) -> None:
    """
    Discriminating test: fake emits tool_use for get_schema, server executes the
    REAL get_schema tool against model-alpha, feeds result back, fake returns text.
    Assert the schema title appears in the tool_result fed back to Claude.
    """
    tool_use_id = "tu_001"
    responses = _tool_use_then_text(
        "get_schema", {}, tool_use_id, "The schema title is Org Readiness."
    )
    fake = _StrictFakeClient(responses)

    from app.clients.anthropic_client import get_anthropic_client
    from app.main import app

    app.dependency_overrides[get_anthropic_client] = lambda: fake
    try:
        resp = await live_server.post(
            "/api/test/session",
            json={
                "model_id": "model-alpha",
                "messages": [{"role": "user", "content": "What fields does this model have?"}],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["tool_calls_made"] == 1

        # The second call to Claude must include a tool_result with the right tool_use_id
        assert len(fake.calls) == 2, "Expected exactly 2 Claude calls (1 tool_use + 1 text)"
        second_call_messages = fake.calls[1]["messages"]

        # Find the tool_result block in the message history
        tool_results = []
        for msg in second_call_messages:
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        tool_results.append(block)

        assert tool_results, "No tool_result block found in second Claude call"
        assert tool_results[0]["tool_use_id"] == tool_use_id

        # The tool_result content must include the real schema title
        result_text = tool_results[0]["content"]
        assert "Org Readiness" in result_text, (
            f"Expected schema title in tool_result, got: {result_text[:200]}"
        )
    finally:
        app.dependency_overrides.pop(get_anthropic_client, None)


@pytest.mark.asyncio
async def test_session_respects_max_iterations(live_server: AsyncClient) -> None:
    """If Claude keeps requesting tools, the loop must break at the cap."""
    # Build 10 consecutive tool_use responses — more than _MAX_TOOL_ITERATIONS
    tool_responses = []
    for i in range(10):
        tu = MagicMock()
        tu.type = "tool_use"
        tu.id = f"tu_{i:03d}"
        tu.name = "get_schema"
        tu.input = {}
        r = MagicMock()
        r.content = [tu]
        r.stop_reason = "tool_use"
        tool_responses.append(r)
    # Final text response
    tool_responses.append(_text_response("Done."))

    fake = _StrictFakeClient(tool_responses)
    from app.clients.anthropic_client import get_anthropic_client
    from app.main import app

    app.dependency_overrides[get_anthropic_client] = lambda: fake
    try:
        resp = await live_server.post(
            "/api/test/session",
            json={
                "model_id": "model-alpha",
                "messages": [{"role": "user", "content": "Loop test"}],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        # Must not exceed the cap
        from app.api.test_session import _MAX_TOOL_ITERATIONS

        assert body["tool_calls_made"] <= _MAX_TOOL_ITERATIONS
    finally:
        app.dependency_overrides.pop(get_anthropic_client, None)


@pytest.mark.asyncio
async def test_session_tools_include_model_tools(live_server: AsyncClient) -> None:
    """The tools passed to Claude must include the model's enabled tools."""
    fake = _StrictFakeClient([_text_response("OK")])
    from app.clients.anthropic_client import get_anthropic_client
    from app.main import app

    app.dependency_overrides[get_anthropic_client] = lambda: fake
    try:
        await live_server.post(
            "/api/test/session",
            json={
                "model_id": "model-crud",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert fake.calls
        passed_tools = {t["name"] for t in fake.calls[0].get("tools", [])}
        # model-crud has both schema_only and crud tools
        assert "get_schema" in passed_tools
        assert "create_instance" in passed_tools
    finally:
        app.dependency_overrides.pop(get_anthropic_client, None)


@pytest.mark.asyncio
async def test_session_uses_snake_case_input_schema(live_server: AsyncClient) -> None:
    """Anthropic API requires input_schema (not inputSchema) for each tool."""
    fake = _StrictFakeClient([_text_response("OK")])
    from app.clients.anthropic_client import get_anthropic_client
    from app.main import app

    app.dependency_overrides[get_anthropic_client] = lambda: fake
    try:
        await live_server.post(
            "/api/test/session",
            json={
                "model_id": "model-alpha",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        tools = fake.calls[0].get("tools", [])
        for tool in tools:
            assert "input_schema" in tool, f"Tool {tool['name']} missing input_schema"
            assert "inputSchema" not in tool, f"Tool {tool['name']} has camelCase inputSchema"
    finally:
        app.dependency_overrides.pop(get_anthropic_client, None)


@pytest.mark.asyncio
async def test_session_draft_model_accessible(live_server: AsyncClient) -> None:
    """Test-session must work on draft models that the MCP gateway would reject."""
    # Create a fresh draft model
    created = (
        await live_server.post(
            "/api/models",
            json={
                "name": "Draft for test-session",
                "json_schema": {
                    "type": "object",
                    "title": "DraftTest",
                    "properties": {"x": {"type": "integer"}},
                },
                "enabled_tool_classes": ["schema_only"],
            },
        )
    ).json()
    draft_id = created["id"]
    assert created["status"] == "draft"

    fake = _StrictFakeClient([_text_response("Schema loaded.")])
    from app.clients.anthropic_client import get_anthropic_client
    from app.main import app

    app.dependency_overrides[get_anthropic_client] = lambda: fake
    try:
        resp = await live_server.post(
            "/api/test/session",
            json={
                "model_id": draft_id,
                "messages": [{"role": "user", "content": "Show the schema."}],
            },
        )
        assert resp.status_code == 200, "Test-session must work on draft models"
    finally:
        app.dependency_overrides.pop(get_anthropic_client, None)
