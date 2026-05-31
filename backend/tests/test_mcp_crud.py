"""
Phase 3 CRUD integration tests.

Uses model-crud (Sensor Reading, enabled_tool_classes=["schema_only","crud"]) seeded
by test_mcp_gateway.py's seeded_models autouse fixture.

All assertions drive the MCP client exclusively — no direct-DB reads.
Tests are additive (create new instances rather than assuming a clean slate),
so count-sensitive assertions use ids we created in the test, not absolute counts.
"""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

MODEL_ID = "model-crud"
URL = f"http://test/mcp/{MODEL_ID}"

VALID_READING = {"sensor_id": "S-001", "value": 23.5, "unit": "C"}
VALID_READING_2 = {"sensor_id": "S-002", "value": 101.3, "unit": "Pa"}
INVALID_READING = {"sensor_id": "S-003"}  # missing required value + unit


# ── Helper ────────────────────────────────────────────────────────────────────


async def _session(client: AsyncClient) -> tuple[ClientSession, AsyncClient]:
    """Not used as a context manager — callers use streamable_http_client directly."""
    raise NotImplementedError  # marker only


# ── Tool presence ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_crud_tools_present_on_crud_model(live_server: AsyncClient) -> None:
    async with streamable_http_client(URL, http_client=live_server) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            # All six CRUD tools present
            assert "create_instance" in names
            assert "get_instance" in names
            assert "update_instance" in names
            assert "delete_instance" in names
            assert "list_instances" in names
            assert "query_instances" in names
            # Schema-only tools also present (both classes enabled)
            assert "get_schema" in names


@pytest.mark.asyncio
async def test_crud_tools_absent_on_schema_only_model(live_server: AsyncClient) -> None:
    """model-alpha has only schema_only — CRUD tools must not appear."""
    url = "http://test/mcp/model-alpha"
    async with streamable_http_client(url, http_client=live_server) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert "create_instance" not in names
            assert "get_instance" not in names


# ── Happy-path lifecycle ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_instance_valid(live_server: AsyncClient) -> None:
    async with streamable_http_client(URL, http_client=live_server) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            result = await session.call_tool("create_instance", VALID_READING)
            body = json.loads(result.content[0].text)  # type: ignore[union-attr]
            assert body["created"] is True
            assert "id" in body
            assert body["data"] == VALID_READING


@pytest.mark.asyncio
async def test_create_then_get(live_server: AsyncClient) -> None:
    async with streamable_http_client(URL, http_client=live_server) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            created = json.loads(
                (await session.call_tool("create_instance", VALID_READING)).content[0].text  # type: ignore[union-attr]
            )
            instance_id = created["id"]

            fetched = json.loads(
                (await session.call_tool("get_instance", {"instance_id": instance_id})).content[0].text  # type: ignore[union-attr]
            )
            assert fetched["id"] == instance_id
            assert fetched["model_id"] == MODEL_ID
            assert fetched["data"] == VALID_READING


@pytest.mark.asyncio
async def test_update_instance(live_server: AsyncClient) -> None:
    async with streamable_http_client(URL, http_client=live_server) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            created = json.loads(
                (await session.call_tool("create_instance", VALID_READING)).content[0].text  # type: ignore[union-attr]
            )
            instance_id = created["id"]

            new_data = {**VALID_READING, "value": 99.9}
            updated = json.loads(
                (
                    await session.call_tool(
                        "update_instance", {"instance_id": instance_id, "data": new_data}
                    )
                ).content[0].text  # type: ignore[union-attr]
            )
            assert updated["updated"] is True
            assert updated["data"]["value"] == 99.9

            # get reflects the change
            fetched = json.loads(
                (await session.call_tool("get_instance", {"instance_id": instance_id})).content[0].text  # type: ignore[union-attr]
            )
            assert fetched["data"]["value"] == 99.9


@pytest.mark.asyncio
async def test_delete_instance_and_get_fails(live_server: AsyncClient) -> None:
    """Soft-delete: after delete, get returns not-found error."""
    async with streamable_http_client(URL, http_client=live_server) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            created = json.loads(
                (await session.call_tool("create_instance", VALID_READING)).content[0].text  # type: ignore[union-attr]
            )
            instance_id = created["id"]

            del_result = json.loads(
                (await session.call_tool("delete_instance", {"instance_id": instance_id})).content[0].text  # type: ignore[union-attr]
            )
            assert del_result["deleted"] is True

            # get must now return an error
            get_result = await session.call_tool("get_instance", {"instance_id": instance_id})
            assert get_result.isError


@pytest.mark.asyncio
async def test_delete_instance_excluded_from_list(live_server: AsyncClient) -> None:
    """Deleted instance must not appear in list_instances."""
    async with streamable_http_client(URL, http_client=live_server) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            created = json.loads(
                (await session.call_tool("create_instance", VALID_READING)).content[0].text  # type: ignore[union-attr]
            )
            instance_id = created["id"]

            await session.call_tool("delete_instance", {"instance_id": instance_id})

            listed = json.loads(
                (await session.call_tool("list_instances", {})).content[0].text  # type: ignore[union-attr]
            )
            ids = {inst["id"] for inst in listed["instances"]}
            assert instance_id not in ids


# ── Validation error path ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_instance_invalid_data(live_server: AsyncClient) -> None:
    async with streamable_http_client(URL, http_client=live_server) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            result = await session.call_tool("create_instance", INVALID_READING)
            body = json.loads(result.content[0].text)  # type: ignore[union-attr]
            assert body["created"] is False
            assert body["errors"]


@pytest.mark.asyncio
async def test_update_instance_invalid_data(live_server: AsyncClient) -> None:
    async with streamable_http_client(URL, http_client=live_server) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            created = json.loads(
                (await session.call_tool("create_instance", VALID_READING)).content[0].text  # type: ignore[union-attr]
            )
            instance_id = created["id"]
            result = await session.call_tool(
                "update_instance",
                {"instance_id": instance_id, "data": INVALID_READING},
            )
            body = json.loads(result.content[0].text)  # type: ignore[union-attr]
            assert body["updated"] is False
            assert body["errors"]


# ── Isolation: cross-model access is forbidden ────────────────────────────────


@pytest.mark.asyncio
async def test_cross_model_instance_not_accessible(live_server: AsyncClient) -> None:
    """An instance_id created under model-crud must not be visible under model-alpha."""
    crud_url = URL
    alpha_url = "http://test/mcp/model-alpha"

    # Create an instance on model-crud
    async with streamable_http_client(crud_url, http_client=live_server) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            created = json.loads(
                (await session.call_tool("create_instance", VALID_READING)).content[0].text  # type: ignore[union-attr]
            )
    instance_id = created["id"]

    # Attempt to call get_instance on model-alpha (CRUD not enabled → method error)
    async with streamable_http_client(alpha_url, http_client=live_server) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            # model-alpha doesn't have crud enabled — call should return error
            result = await session.call_tool("get_instance", {"instance_id": instance_id})
            assert result.isError


# ── Query ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_query_instances_by_filter(live_server: AsyncClient) -> None:
    async with streamable_http_client(URL, http_client=live_server) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            # Create a distinctively-named instance
            distinct = {"sensor_id": "DISTINCT-XYZ", "value": 55.5, "unit": "C"}
            await session.call_tool("create_instance", distinct)

            result = json.loads(
                (
                    await session.call_tool(
                        "query_instances",
                        {"filters": {"sensor_id": "DISTINCT-XYZ"}},
                    )
                ).content[0].text  # type: ignore[union-attr]
            )
            ids = [inst["id"] for inst in result["instances"]]
            assert len(ids) >= 1
            assert all(inst["data"]["sensor_id"] == "DISTINCT-XYZ" for inst in result["instances"])


@pytest.mark.asyncio
async def test_list_instances_pagination(live_server: AsyncClient) -> None:
    async with streamable_http_client(URL, http_client=live_server) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            # Create two more instances to ensure pagination has something to page through
            await session.call_tool("create_instance", VALID_READING)
            await session.call_tool("create_instance", VALID_READING_2)

            page1 = json.loads(
                (await session.call_tool("list_instances", {"limit": 1, "offset": 0})).content[0].text  # type: ignore[union-attr]
            )
            page2 = json.loads(
                (await session.call_tool("list_instances", {"limit": 1, "offset": 1})).content[0].text  # type: ignore[union-attr]
            )
            assert len(page1["instances"]) == 1
            assert len(page2["instances"]) == 1
            assert page1["instances"][0]["id"] != page2["instances"][0]["id"]
            assert page1["total"] == page2["total"]  # same total
