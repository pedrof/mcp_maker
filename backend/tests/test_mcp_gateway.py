"""
Phase 2 MCP gateway integration tests.

Spins a real Postgres (via testcontainers in conftest), publishes two models,
then connects with the SDK's streamable_http_client to assert:
  - initialize succeeds
  - list_tools, list_resources, list_prompts reflect the correct model
  - call_tool("get_schema") returns the right schema (proves per-model dispatch)
  - Two concurrent models return their own data (isolation check)

Implementation notes:
  - All app.* imports are deferred inside fixtures/functions (see conftest.py gotchas note).
  - Seeding uses a fresh SQLAlchemy engine (not the module-level pool) to avoid
    asyncpg "Future attached to different loop" errors when the session-scope fixture
    runs in a different loop context than function-scope tests.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

import anyio
import pytest
import pytest_asyncio
from httpx import AsyncClient
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# ── Schema constants ──────────────────────────────────────────────────────────

SCHEMA_A = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "title": "Org Readiness",
    "properties": {
        "division": {"type": "string"},
        "personnel_pct": {"type": "number", "minimum": 0, "maximum": 100},
    },
    "required": ["division", "personnel_pct"],
}

SCHEMA_B = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "title": "Fleet Asset",
    "properties": {
        "asset_id": {"type": "string"},
        "status": {"type": "string", "enum": ["active", "maintenance", "decommissioned"]},
    },
    "required": ["asset_id", "status"],
}


# ── Seed helpers ──────────────────────────────────────────────────────────────


async def _seed_rows(rows: list[dict]) -> None:
    """
    Insert model rows using a fresh async engine.

    Using a fresh engine (not the module-level pool) avoids asyncpg
    "Future attached to different loop" errors between session-scope and
    function-scope event loops.
    """
    # Deferred imports — must happen after DATABASE_URL env var is set
    from app.models.model import ForgeModel, ModelStatus, Visibility  # noqa: F401 (registers Base)

    db_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(db_url, pool_pre_ping=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with Session() as db:
            for row in rows:
                db.add(ForgeModel(**row))
            await db.commit()
    finally:
        await engine.dispose()


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="session", autouse=True)
async def seeded_models(live_server: AsyncClient) -> None:
    """Seed test models once for the session. live_server ensures DB + lifespan are up."""
    now = datetime.utcnow()
    await _seed_rows([
        {
            "id": "model-alpha",
            "name": "Org Readiness",
            "description": "Test model: Org Readiness",
            "json_schema": SCHEMA_A,
            "system_prompt": "You are an org readiness advisor.",
            "enabled_tool_classes": ["schema_only"],
            "metrics_config": {},
            "visibility": "public",
            "owner_sub": "test-user",
            "status": "published",
            "current_version": 1,
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": "model-beta",
            "name": "Fleet Asset",
            "description": "Test model: Fleet Asset",
            "json_schema": SCHEMA_B,
            "system_prompt": None,
            "enabled_tool_classes": ["schema_only"],
            "metrics_config": {},
            "visibility": "public",
            "owner_sub": "test-user",
            "status": "published",
            "current_version": 1,
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": "model-draft",
            "name": "Draft Model",
            "description": None,
            "json_schema": {"type": "object"},
            "system_prompt": None,
            "enabled_tool_classes": [],
            "metrics_config": {},
            "visibility": "public",
            "owner_sub": "test-user",
            "status": "draft",  # deliberately unpublished
            "current_version": 1,
            "created_at": now,
            "updated_at": now,
        },
    ])


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
