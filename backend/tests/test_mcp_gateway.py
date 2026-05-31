"""
Phase 2 MCP gateway integration tests.

All test models are seeded by conftest.py's seeded_models autouse fixture.
All app.* imports are deferred inside fixtures/functions (see conftest.py).
"""

from __future__ import annotations

import json

import anyio
import pytest
from httpx import AsyncClient
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_still_ok(live_server: AsyncClient) -> None:
    resp = await live_server.get("/health")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_mcp_initialize_model_alpha(live_server: AsyncClient) -> None:
    async with streamable_http_client(
        "http://test/mcp/model-alpha", http_client=live_server
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            result = await session.initialize()
            assert result.serverInfo.name == "forge-gateway"


@pytest.mark.asyncio
async def test_list_tools_schema_only(live_server: AsyncClient) -> None:
    async with streamable_http_client(
        "http://test/mcp/model-alpha", http_client=live_server
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool_names = {t.name for t in tools.tools}
            assert "get_schema" in tool_names
            assert "describe_model" in tool_names
            assert "validate_instance" in tool_names
            assert "generate_example" in tool_names
            # CRUD tools must NOT appear on a schema_only model
            assert "create_instance" not in tool_names


@pytest.mark.asyncio
async def test_call_tool_get_schema_model_alpha(live_server: AsyncClient) -> None:
    """Core dispatch test: get_schema must return model-alpha's schema."""
    async with streamable_http_client(
        "http://test/mcp/model-alpha", http_client=live_server
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("get_schema", {})
            assert result.content
            schema = json.loads(result.content[0].text)  # type: ignore[union-attr]
            assert schema.get("title") == "Org Readiness"
            assert "personnel_pct" in schema.get("properties", {})


@pytest.mark.asyncio
async def test_call_tool_get_schema_model_beta(live_server: AsyncClient) -> None:
    """Core dispatch test: get_schema must return model-beta's schema."""
    async with streamable_http_client(
        "http://test/mcp/model-beta", http_client=live_server
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("get_schema", {})
            assert result.content
            schema = json.loads(result.content[0].text)  # type: ignore[union-attr]
            assert schema.get("title") == "Fleet Asset"
            assert "asset_id" in schema.get("properties", {})


@pytest.mark.asyncio
async def test_per_model_isolation_concurrent(live_server: AsyncClient) -> None:
    """
    Both models queried concurrently; each must get its own schema.
    Proves ContextVar isolation across concurrent stateless requests.
    """
    alpha_schema: dict = {}
    beta_schema: dict = {}

    async def fetch_alpha() -> None:
        async with streamable_http_client(
            "http://test/mcp/model-alpha", http_client=live_server
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("get_schema", {})
                alpha_schema.update(json.loads(result.content[0].text))  # type: ignore[union-attr]

    async def fetch_beta() -> None:
        async with streamable_http_client(
            "http://test/mcp/model-beta", http_client=live_server
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("get_schema", {})
                beta_schema.update(json.loads(result.content[0].text))  # type: ignore[union-attr]

    async with anyio.create_task_group() as tg:
        tg.start_soon(fetch_alpha)
        tg.start_soon(fetch_beta)

    assert alpha_schema.get("title") == "Org Readiness"
    assert beta_schema.get("title") == "Fleet Asset"


@pytest.mark.asyncio
async def test_list_resources(live_server: AsyncClient) -> None:
    async with streamable_http_client(
        "http://test/mcp/model-alpha", http_client=live_server
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            resources = await session.list_resources()
            uris = {str(r.uri) for r in resources.resources}
            assert "schema://model-alpha" in uris
            assert "model://model-alpha" in uris


@pytest.mark.asyncio
async def test_list_prompts_with_system_prompt(live_server: AsyncClient) -> None:
    async with streamable_http_client(
        "http://test/mcp/model-alpha", http_client=live_server
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            prompts = await session.list_prompts()
            assert any(p.name == "strategize" for p in prompts.prompts)


@pytest.mark.asyncio
async def test_list_prompts_no_system_prompt(live_server: AsyncClient) -> None:
    async with streamable_http_client(
        "http://test/mcp/model-beta", http_client=live_server
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            prompts = await session.list_prompts()
            assert prompts.prompts == []


@pytest.mark.asyncio
async def test_validate_instance_valid(live_server: AsyncClient) -> None:
    async with streamable_http_client(
        "http://test/mcp/model-alpha", http_client=live_server
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "validate_instance",
                {"data": {"division": "Alpha", "personnel_pct": 85.0}},
            )
            body = json.loads(result.content[0].text)  # type: ignore[union-attr]
            assert body["valid"] is True


@pytest.mark.asyncio
async def test_validate_instance_invalid(live_server: AsyncClient) -> None:
    async with streamable_http_client(
        "http://test/mcp/model-alpha", http_client=live_server
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "validate_instance",
                {"data": {"personnel_pct": 85.0}},  # missing required "division"
            )
            body = json.loads(result.content[0].text)  # type: ignore[union-attr]
            assert body["valid"] is False
            assert body["errors"]


@pytest.mark.asyncio
async def test_generate_example(live_server: AsyncClient) -> None:
    async with streamable_http_client(
        "http://test/mcp/model-alpha", http_client=live_server
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("generate_example", {})
            example = json.loads(result.content[0].text)  # type: ignore[union-attr]
            assert "division" in example
            assert "personnel_pct" in example


@pytest.mark.asyncio
async def test_unpublished_model_returns_error(live_server: AsyncClient) -> None:
    async with streamable_http_client(
        "http://test/mcp/model-draft", http_client=live_server
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("get_schema", {})
            assert result.isError
