"""
Phase 8 auth integration tests.

Two independent planes:

1. Authoring plane: owner isolation via get_current_owner.
   Tests that /api/* routes scope data by owner — first real exercise of the
   WHERE owner_sub clause (previous phases ran everything as one owner).

2. Data plane: per-model bearer key enforcement on /mcp/{id}.
   protected model → 401 without key, 200 with correct key.
   public model → unaffected.
"""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "title": "Auth Test",
    "properties": {"name": {"type": "string"}},
}

# ── Owner isolation ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_owner_a_cannot_see_owner_b_models(live_server: AsyncClient) -> None:
    """Models created by owner-B must not appear in owner-A's list."""
    from app.api.deps import get_current_owner
    from app.main import app

    # Create a model as owner-b
    app.dependency_overrides[get_current_owner] = lambda: "owner-b"
    try:
        resp_b = await live_server.post(
            "/api/models",
            json={"name": "Owner B Model", "json_schema": SCHEMA},
        )
        assert resp_b.status_code == 201
        b_id = resp_b.json()["id"]
    finally:
        app.dependency_overrides[get_current_owner] = lambda: "anonymous"

    # List as owner-a (anonymous) — owner-b's model must not appear
    listed = (await live_server.get("/api/models")).json()
    ids = [m["id"] for m in listed]
    assert b_id not in ids, "owner-b model leaked into owner-a listing"


@pytest.mark.asyncio
async def test_owner_a_cannot_get_owner_b_model(live_server: AsyncClient) -> None:
    """GET on another owner's model returns 404."""
    from app.api.deps import get_current_owner
    from app.main import app

    app.dependency_overrides[get_current_owner] = lambda: "owner-b"
    try:
        created = (await live_server.post(
            "/api/models",
            json={"name": "B's Private Model", "json_schema": SCHEMA},
        )).json()
        b_id = created["id"]
    finally:
        app.dependency_overrides[get_current_owner] = lambda: "anonymous"

    # Try to GET as owner-a
    resp = await live_server.get(f"/api/models/{b_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_owner_a_cannot_patch_owner_b_model(live_server: AsyncClient) -> None:
    """PATCH on another owner's model returns 404."""
    from app.api.deps import get_current_owner
    from app.main import app

    app.dependency_overrides[get_current_owner] = lambda: "owner-b"
    try:
        created = (await live_server.post(
            "/api/models",
            json={"name": "B's Patch Target", "json_schema": SCHEMA},
        )).json()
        b_id = created["id"]
    finally:
        app.dependency_overrides[get_current_owner] = lambda: "anonymous"

    resp = await live_server.patch(f"/api/models/{b_id}", json={"name": "Hijacked"})
    assert resp.status_code == 404


# ── Gateway bearer key enforcement ───────────────────────────────────────────


async def _create_and_publish(
    client: AsyncClient, visibility: str = "public"
) -> tuple[str, str | None]:
    """Create + publish a model; return (model_id, api_key or None)."""
    created = (await client.post(
        "/api/models",
        json={"name": f"Key test {visibility}", "json_schema": SCHEMA,
              "visibility": visibility, "enabled_tool_classes": ["schema_only"]},
    )).json()
    model_id = created["id"]
    pub = (await client.post(f"/api/models/{model_id}/publish")).json()
    return model_id, pub.get("api_key")


@pytest.mark.asyncio
async def test_protected_model_requires_key(live_server: AsyncClient) -> None:
    """A protected model returns 401 when no key is provided."""
    model_id, api_key = await _create_and_publish(live_server, "protected")
    assert api_key is not None, "publish should return api_key for protected models"

    # The MCP client calls raise_for_status() on the POST response, so a 401
    # propagates as an HTTP exception before the MCP protocol layer.
    # Test at the raw HTTP level — the gateway must return 401.
    async with AsyncClient(
        transport=ASGITransport(app=_app()),
        base_url="http://test",
        timeout=10.0,
    ) as no_auth:
        # Any POST to /mcp/{id} without auth should be rejected
        resp = await no_auth.post(
            f"/mcp/{model_id}",
            content=b'{"jsonrpc":"2.0","method":"initialize","id":1,"params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}',
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_protected_model_with_correct_key_succeeds(live_server: AsyncClient) -> None:
    """A protected model is accessible with the correct bearer key."""
    model_id, api_key = await _create_and_publish(live_server, "protected")
    assert api_key is not None

    async with AsyncClient(
        transport=ASGITransport(app=_app()),
        base_url="http://test",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10.0,
    ) as authed:
        async with streamable_http_client(
            f"http://test/mcp/{model_id}", http_client=authed
        ) as (r, w, _):
            async with ClientSession(r, w) as session:
                await session.initialize()
                result = await session.call_tool("get_schema", {})
                assert not result.isError
                schema = json.loads(result.content[0].text)  # type: ignore[union-attr]
                assert schema.get("title") == "Auth Test"


@pytest.mark.asyncio
async def test_protected_model_wrong_key_returns_401(live_server: AsyncClient) -> None:
    """A protected model returns 401 for a wrong key."""
    model_id, _ = await _create_and_publish(live_server, "protected")

    async with AsyncClient(
        transport=ASGITransport(app=_app()),
        base_url="http://test",
        headers={"Authorization": "Bearer wrongkey"},
        timeout=10.0,
    ) as wrong_auth:
        resp = await wrong_auth.post(
            f"/mcp/{model_id}",
            content=b'{"jsonrpc":"2.0","method":"initialize","id":1,"params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}',
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_public_model_needs_no_key(live_server: AsyncClient) -> None:
    """Public models remain accessible without any Authorization header."""
    # model-alpha (seeded, published, public) should work fine without a key
    async with streamable_http_client(
        "http://test/mcp/model-alpha", http_client=live_server
    ) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            result = await session.call_tool("get_schema", {})
            assert not result.isError


@pytest.mark.asyncio
async def test_publish_returns_no_key_for_public_model(live_server: AsyncClient) -> None:
    """Publishing a public model does not return an api_key."""
    _, api_key = await _create_and_publish(live_server, "public")
    assert api_key is None


@pytest.mark.asyncio
async def test_key_stable_across_republish(live_server: AsyncClient) -> None:
    """Re-publishing a protected model does not rotate the key (generate-once-if-null)."""
    model_id, first_key = await _create_and_publish(live_server, "protected")
    assert first_key is not None

    # Unpublish then re-publish
    await live_server.post(f"/api/models/{model_id}/unpublish")
    pub2 = (await live_server.post(f"/api/models/{model_id}/publish")).json()
    second_key = pub2.get("api_key")
    # Key already exists — not regenerated, not returned again
    assert second_key is None, "key should not be returned again on re-publish"

    # The original key still works
    async with AsyncClient(
        transport=ASGITransport(app=_app()),
        base_url="http://test",
        headers={"Authorization": f"Bearer {first_key}"},
        timeout=10.0,
    ) as authed:
        async with streamable_http_client(
            f"http://test/mcp/{model_id}", http_client=authed
        ) as (r, w, _):
            async with ClientSession(r, w) as session:
                await session.initialize()
                result = await session.call_tool("get_schema", {})
                assert not result.isError


def _app():  # type: ignore[return]
    """Deferred import so app.* is only loaded after DATABASE_URL is set."""
    from app.main import app
    return app
