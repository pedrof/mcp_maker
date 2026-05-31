"""
Phase 4 Scenario engine integration tests.

Uses model-scenario (enabled_tool_classes=["schema_only","crud","scenario"]),
metrics_config:
  division_count:      {agg: count}
  avg_personnel_pct:   {agg: avg, field: personnel_pct}
  max_personnel_pct:   {agg: max, field: personnel_pct}
  total_personnel_pct: {agg: sum, field: personnel_pct}

Tests are driven entirely through the MCP client.
Discriminating assertion: full scenario lifecycle does NOT modify live instances.
"""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

MODEL_ID = "model-scenario"
URL = f"http://test/mcp/{MODEL_ID}"

# Known baseline instances created at session start by _create_baseline_instances
BASELINE_DIVISIONS = [
    {"division": "Alpha", "personnel_pct": 80.0},
    {"division": "Bravo", "personnel_pct": 60.0},
    {"division": "Charlie", "personnel_pct": 40.0},
]


# ── Baseline setup fixture ────────────────────────────────────────────────────


@pytest.fixture(scope="session", autouse=True)
def _create_baseline_instances(live_server: AsyncClient) -> None:
    """Synchronous proxy so this runs before the first scenario test.

    Creates three deterministic instances on model-scenario. Session-scoped
    so it runs once; the handle is kept here to avoid polluting conftest.
    The fixture is sync to avoid any event-loop ordering issues.
    """
    # We delegate to a separate async helper via asyncio
    import asyncio

    asyncio.get_event_loop().run_until_complete(
        _async_create_baseline(live_server)
    )


async def _async_create_baseline(client: AsyncClient) -> None:
    async with streamable_http_client(URL, http_client=client) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            for div in BASELINE_DIVISIONS:
                await session.call_tool("create_instance", div)


# ── Helper ────────────────────────────────────────────────────────────────────


async def _mcp(client: AsyncClient, tool: str, args: dict) -> dict:
    async with streamable_http_client(URL, http_client=client) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            result = await session.call_tool(tool, args)
    return json.loads(result.content[0].text)  # type: ignore[union-attr]


# ── Tool presence ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scenario_tools_present(live_server: AsyncClient) -> None:
    async with streamable_http_client(URL, http_client=live_server) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert "create_scenario" in names
            assert "apply_change" in names
            assert "compute_metrics" in names
            assert "compare_to_baseline" in names
            assert "reset_scenario" in names


@pytest.mark.asyncio
async def test_scenario_tools_absent_on_schema_only_model(live_server: AsyncClient) -> None:
    url = "http://test/mcp/model-alpha"
    async with streamable_http_client(url, http_client=live_server) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert "create_scenario" not in names


# ── create_scenario ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_scenario_returns_baseline_metrics(live_server: AsyncClient) -> None:
    body = await _mcp(live_server, "create_scenario", {"name": "Test baseline"})
    assert "scenario_id" in body
    assert body["snapshot_size"] >= 3  # at least our 3 baseline instances
    metrics = body["baseline_metrics"]
    assert metrics["division_count"] >= 3
    assert isinstance(metrics["avg_personnel_pct"], float)
    assert isinstance(metrics["max_personnel_pct"], float)
    assert isinstance(metrics["total_personnel_pct"], float)


# ── apply_change ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_apply_change_add(live_server: AsyncClient) -> None:
    created = await _mcp(live_server, "create_scenario", {"name": "Add test"})
    sid = created["scenario_id"]

    body = await _mcp(
        live_server, "apply_change",
        {"scenario_id": sid, "op": "add", "data": {"division": "Delta", "personnel_pct": 95.0}},
    )
    assert body["applied"] is True
    assert body["total_changes"] == 1


@pytest.mark.asyncio
async def test_apply_change_update(live_server: AsyncClient) -> None:
    """Update requires an instance_id present in the baseline snapshot."""
    # First, grab a real instance_id from the snapshot
    created = await _mcp(live_server, "create_scenario", {"name": "Update test"})
    sid = created["scenario_id"]
    snap_size = created["snapshot_size"]
    assert snap_size >= 1

    # Get the first snapshot instance_id via compute_metrics (no changes yet works too)
    # Actually we need to look at list_instances to find an id
    async with streamable_http_client(URL, http_client=live_server) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            listed = json.loads(
                (await session.call_tool("list_instances", {"limit": 1})).content[0].text  # type: ignore[union-attr]
            )
    instance_id = listed["instances"][0]["id"]

    body = await _mcp(
        live_server, "apply_change",
        {
            "scenario_id": sid,
            "op": "update",
            "instance_id": instance_id,
            "data": {"division": "Alpha-UPDATED", "personnel_pct": 99.0},
        },
    )
    assert body["applied"] is True


@pytest.mark.asyncio
async def test_apply_change_remove(live_server: AsyncClient) -> None:
    created = await _mcp(live_server, "create_scenario", {"name": "Remove test"})
    sid = created["scenario_id"]

    async with streamable_http_client(URL, http_client=live_server) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            listed = json.loads(
                (await session.call_tool("list_instances", {"limit": 1})).content[0].text  # type: ignore[union-attr]
            )
    instance_id = listed["instances"][0]["id"]

    body = await _mcp(
        live_server, "apply_change",
        {"scenario_id": sid, "op": "remove", "instance_id": instance_id},
    )
    assert body["applied"] is True


# ── compute_metrics ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_compute_metrics_after_add_increases_count(live_server: AsyncClient) -> None:
    created = await _mcp(live_server, "create_scenario", {"name": "Compute after add"})
    sid = created["scenario_id"]
    baseline_count = created["baseline_metrics"]["division_count"]

    await _mcp(
        live_server, "apply_change",
        {"scenario_id": sid, "op": "add", "data": {"division": "Extra", "personnel_pct": 50.0}},
    )
    metrics_body = await _mcp(live_server, "compute_metrics", {"scenario_id": sid})
    assert metrics_body["metrics"]["division_count"] == baseline_count + 1


@pytest.mark.asyncio
async def test_compute_metrics_after_remove_decreases_count(live_server: AsyncClient) -> None:
    created = await _mcp(live_server, "create_scenario", {"name": "Compute after remove"})
    sid = created["scenario_id"]
    baseline_count = created["baseline_metrics"]["division_count"]

    async with streamable_http_client(URL, http_client=live_server) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            listed = json.loads(
                (await session.call_tool("list_instances", {"limit": 1})).content[0].text  # type: ignore[union-attr]
            )
    iid = listed["instances"][0]["id"]

    await _mcp(live_server, "apply_change", {"scenario_id": sid, "op": "remove", "instance_id": iid})
    metrics_body = await _mcp(live_server, "compute_metrics", {"scenario_id": sid})
    assert metrics_body["metrics"]["division_count"] == baseline_count - 1


# ── compare_to_baseline ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_compare_to_baseline_shows_delta(live_server: AsyncClient) -> None:
    created = await _mcp(live_server, "create_scenario", {"name": "Compare test"})
    sid = created["scenario_id"]

    await _mcp(
        live_server, "apply_change",
        {"scenario_id": sid, "op": "add", "data": {"division": "New", "personnel_pct": 100.0}},
    )
    cmp_body = await _mcp(live_server, "compare_to_baseline", {"scenario_id": sid})
    comp = cmp_body["comparison"]

    # division_count must have increased by exactly 1
    assert comp["division_count"]["delta"] == 1
    assert comp["division_count"]["current"] == comp["division_count"]["baseline"] + 1

    # total_personnel_pct must have increased by 100.0
    assert comp["total_personnel_pct"]["delta"] == pytest.approx(100.0)


# ── reset_scenario ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reset_restores_baseline(live_server: AsyncClient) -> None:
    created = await _mcp(live_server, "create_scenario", {"name": "Reset test"})
    sid = created["scenario_id"]
    baseline_count = created["baseline_metrics"]["division_count"]

    await _mcp(
        live_server, "apply_change",
        {"scenario_id": sid, "op": "add", "data": {"division": "Temp", "personnel_pct": 50.0}},
    )
    after_add = await _mcp(live_server, "compute_metrics", {"scenario_id": sid})
    assert after_add["metrics"]["division_count"] == baseline_count + 1

    reset_body = await _mcp(live_server, "reset_scenario", {"scenario_id": sid})
    assert reset_body["reset"] is True
    assert reset_body["baseline_metrics"]["division_count"] == baseline_count

    after_reset = await _mcp(live_server, "compute_metrics", {"scenario_id": sid})
    assert after_reset["metrics"]["division_count"] == baseline_count


# ── THE discriminating test: live data is unchanged after scenario lifecycle ──


@pytest.mark.asyncio
async def test_scenario_does_not_touch_live_instances(live_server: AsyncClient) -> None:
    """
    Run the full scenario lifecycle (create, add, update, remove, compute, compare, reset).
    Then verify that list_instances on the live model returns the SAME instance ids
    as before the scenario was created. Live data must be byte-for-byte untouched.
    """
    # Capture live state BEFORE the scenario
    async with streamable_http_client(URL, http_client=live_server) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            pre = json.loads(
                (await session.call_tool("list_instances", {"limit": 100})).content[0].text  # type: ignore[union-attr]
            )
    pre_ids = {inst["id"] for inst in pre["instances"]}
    pre_data = {inst["id"]: inst["data"] for inst in pre["instances"]}

    # Run a full scenario lifecycle
    created = await _mcp(live_server, "create_scenario", {"name": "Isolation proof"})
    sid = created["scenario_id"]

    await _mcp(
        live_server, "apply_change",
        {"scenario_id": sid, "op": "add", "data": {"division": "Ghost", "personnel_pct": 1.0}},
    )
    first_id = next(iter(pre_ids))
    await _mcp(
        live_server, "apply_change",
        {
            "scenario_id": sid,
            "op": "update",
            "instance_id": first_id,
            "data": {"division": "MUTATED", "personnel_pct": 0.0},
        },
    )
    await _mcp(live_server, "compute_metrics", {"scenario_id": sid})
    await _mcp(live_server, "compare_to_baseline", {"scenario_id": sid})
    await _mcp(live_server, "reset_scenario", {"scenario_id": sid})

    # Capture live state AFTER the scenario
    async with streamable_http_client(URL, http_client=live_server) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            post = json.loads(
                (await session.call_tool("list_instances", {"limit": 100})).content[0].text  # type: ignore[union-attr]
            )
    post_ids = {inst["id"] for inst in post["instances"]}
    post_data = {inst["id"]: inst["data"] for inst in post["instances"]}

    # Ids are unchanged
    assert pre_ids == post_ids, "Live instance set changed — scenario mutated live data!"
    # Data is unchanged
    for iid in pre_ids:
        assert pre_data[iid] == post_data[iid], (
            f"Instance {iid} data changed — scenario mutated live data!"
        )


# ── Cross-model isolation ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cross_model_scenario_not_accessible(live_server: AsyncClient) -> None:
    """A scenario_id from model-scenario must not be accessible via model-crud."""
    created = await _mcp(live_server, "create_scenario", {"name": "Isolation scenario"})
    sid = created["scenario_id"]

    # model-crud does not have scenario enabled — call should error
    crud_url = "http://test/mcp/model-crud"
    async with streamable_http_client(crud_url, http_client=live_server) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            result = await session.call_tool("compute_metrics", {"scenario_id": sid})
            assert result.isError
