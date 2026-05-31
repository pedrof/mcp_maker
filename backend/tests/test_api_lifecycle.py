"""
Phase 5 Authoring REST API integration tests.

Headline test: REST create→publish→MCP works, then unpublish→MCP errors,
then re-publish with new schema→MCP serves new schema. This proves publish
controls the gateway immediately with no cache lag.

All tests create their own fresh model ids to avoid colliding with seeded_models.
"""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

SCHEMA_V1 = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "title": "Org v1",
    "properties": {"name": {"type": "string"}, "score": {"type": "number"}},
    "required": ["name", "score"],
}
SCHEMA_V2 = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "title": "Org v2 Revised",
    "properties": {
        "name": {"type": "string"},
        "score": {"type": "number"},
        "tier": {"type": "string", "enum": ["gold", "silver", "bronze"]},
    },
    "required": ["name", "score", "tier"],
}


# ── CRUD ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_and_get_draft(live_server: AsyncClient) -> None:
    resp = await live_server.post(
        "/api/models",
        json={
            "name": "Test Draft",
            "json_schema": SCHEMA_V1,
            "enabled_tool_classes": ["schema_only"],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "draft"
    assert body["current_version"] == 0
    model_id = body["id"]

    get_resp = await live_server.get(f"/api/models/{model_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == model_id


@pytest.mark.asyncio
async def test_list_models_includes_new(live_server: AsyncClient) -> None:
    created = (
        await live_server.post(
            "/api/models",
            json={"name": "List Test Model", "json_schema": SCHEMA_V1},
        )
    ).json()
    model_id = created["id"]

    listed = (await live_server.get("/api/models")).json()
    ids = [m["id"] for m in listed]
    assert model_id in ids


@pytest.mark.asyncio
async def test_update_draft(live_server: AsyncClient) -> None:
    created = (
        await live_server.post("/api/models", json={"name": "Update Test", "json_schema": {}})
    ).json()
    model_id = created["id"]

    patch_resp = await live_server.patch(
        f"/api/models/{model_id}",
        json={"name": "Updated Name", "json_schema": SCHEMA_V1},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["name"] == "Updated Name"


@pytest.mark.asyncio
async def test_update_published_returns_409(live_server: AsyncClient) -> None:
    created = (
        await live_server.post(
            "/api/models",
            json={"id": "test-lock-check", "name": "Lock Check", "json_schema": SCHEMA_V1},
        )
    ).json()
    await live_server.post(f"/api/models/{created['id']}/publish")

    patch_resp = await live_server.patch(
        f"/api/models/{created['id']}",
        json={"name": "Attempted edit"},
    )
    assert patch_resp.status_code == 409


@pytest.mark.asyncio
async def test_auto_slug_generation(live_server: AsyncClient) -> None:
    resp = await live_server.post(
        "/api/models",
        json={"name": "My Cool Model 2024!", "json_schema": SCHEMA_V1},
    )
    assert resp.status_code == 201
    assert "my-cool-model-2024" in resp.json()["id"]


# ── Publish / unpublish ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_creates_version(live_server: AsyncClient) -> None:
    created = (
        await live_server.post(
            "/api/models",
            json={"name": "Version Test", "json_schema": SCHEMA_V1},
        )
    ).json()
    model_id = created["id"]

    pub = await live_server.post(f"/api/models/{model_id}/publish")
    assert pub.status_code == 200
    body = pub.json()
    assert body["status"] == "published"
    assert body["version"] == 1
    assert body["mcp_endpoint"] == f"/mcp/{model_id}"

    versions = (await live_server.get(f"/api/models/{model_id}/versions")).json()
    assert len(versions) == 1
    assert versions[0]["version_number"] == 1


@pytest.mark.asyncio
async def test_publish_empty_schema_returns_422(live_server: AsyncClient) -> None:
    created = (
        await live_server.post("/api/models", json={"name": "Empty Schema Test"})
    ).json()
    resp = await live_server.post(f"/api/models/{created['id']}/publish")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_unpublish(live_server: AsyncClient) -> None:
    created = (
        await live_server.post(
            "/api/models", json={"name": "Unpublish Test", "json_schema": SCHEMA_V1}
        )
    ).json()
    model_id = created["id"]
    await live_server.post(f"/api/models/{model_id}/publish")

    resp = await live_server.post(f"/api/models/{model_id}/unpublish")
    assert resp.status_code == 200
    assert resp.json()["status"] == "unpublished"


# ── THE headline test: REST lifecycle controls gateway in real time ───────────


@pytest.mark.asyncio
async def test_publish_controls_gateway(live_server: AsyncClient) -> None:
    """
    create draft → gateway errors (not published)
    publish → gateway serves list_tools / get_schema
    unpublish → gateway errors again
    edit + re-publish → gateway serves NEW schema
    """
    # 1. Create draft
    created = (
        await live_server.post(
            "/api/models",
            json={
                "name": "Gateway Control Test",
                "json_schema": SCHEMA_V1,
                "enabled_tool_classes": ["schema_only"],
            },
        )
    ).json()
    model_id = created["id"]
    mcp_url = f"http://test/mcp/{model_id}"

    # 2. Draft → gateway must error
    async with streamable_http_client(mcp_url, http_client=live_server) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            result = await session.call_tool("get_schema", {})
            assert result.isError, "Draft model should not be served by gateway"

    # 3. Publish
    pub = await live_server.post(f"/api/models/{model_id}/publish")
    assert pub.status_code == 200

    # 4. Published → gateway must serve it
    async with streamable_http_client(mcp_url, http_client=live_server) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            result = await session.call_tool("get_schema", {})
            assert not result.isError
            schema = json.loads(result.content[0].text)  # type: ignore[union-attr]
            assert schema["title"] == "Org v1"

    # 5. Unpublish → gateway must error again
    await live_server.post(f"/api/models/{model_id}/unpublish")
    async with streamable_http_client(mcp_url, http_client=live_server) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            result = await session.call_tool("get_schema", {})
            assert result.isError, "Unpublished model should not be served by gateway"

    # 6. Edit schema (model is now unpublished → PATCH allowed)
    await live_server.patch(
        f"/api/models/{model_id}",
        json={"json_schema": SCHEMA_V2, "name": "Gateway Control Test v2"},
    )

    # 7. Re-publish → version 2 created, gateway serves new schema
    pub2 = await live_server.post(f"/api/models/{model_id}/publish")
    assert pub2.status_code == 200
    assert pub2.json()["version"] == 2

    async with streamable_http_client(mcp_url, http_client=live_server) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            result = await session.call_tool("get_schema", {})
            assert not result.isError
            schema2 = json.loads(result.content[0].text)  # type: ignore[union-attr]
            assert schema2["title"] == "Org v2 Revised"
            assert "tier" in schema2["properties"]

    # 8. Two versions in history
    versions = (await live_server.get(f"/api/models/{model_id}/versions")).json()
    assert len(versions) == 2
    assert versions[0]["version_number"] == 1
    assert versions[1]["version_number"] == 2
    assert versions[0]["json_schema"]["title"] == "Org v1"
    assert versions[1]["json_schema"]["title"] == "Org v2 Revised"


@pytest.mark.asyncio
async def test_not_found_returns_404(live_server: AsyncClient) -> None:
    resp = await live_server.get("/api/models/nonexistent-model-xyz")
    assert resp.status_code == 404
