"""
Test fixtures for FORGE backend integration tests.

Architecture:
  - postgres_container (sync, session) — starts a real Postgres via testcontainers
  - migrated_db (sync, session) — runs Alembic migrations once
  - live_server (async, session) — starts app with session_manager lifecycle
  - seeded_models (async, session, autouse) — inserts test model rows once globally
  - client (async, session) — alias for live_server for test_health.py

Key design decisions:
  1. Alembic's env.py calls asyncio.run() — migrated_db MUST be sync (no outer event loop).
  2. ASGITransport does NOT trigger the ASGI lifespan, so session_manager.run() must
     be started manually.
  3. anyio cancel scopes MUST be entered and exited in the same Task. pytest-asyncio
     finalizes fixtures in a separate finalizer task. We therefore run session_manager
     in a persistent background asyncio.Task and signal it via an asyncio.Event.
  4. All tests use asyncio_default_test_loop_scope = "session" (pyproject.toml) so
     the DB connections, the background task, and the test code all share one event loop.
  5. seeded_models is in conftest.py (not a test file) so it fires before ANY test module,
     regardless of collection order.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

# ── Schema constants for test models ──────────────────────────────────────────

_SCHEMA_ORG_READINESS = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "title": "Org Readiness",
    "properties": {
        "division": {"type": "string"},
        "personnel_pct": {"type": "number", "minimum": 0, "maximum": 100},
    },
    "required": ["division", "personnel_pct"],
}

_SCHEMA_FLEET_ASSET = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "title": "Fleet Asset",
    "properties": {
        "asset_id": {"type": "string"},
        "status": {"type": "string", "enum": ["active", "maintenance", "decommissioned"]},
    },
    "required": ["asset_id", "status"],
}

_SCHEMA_SENSOR = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "title": "Sensor Reading",
    "properties": {
        "sensor_id": {"type": "string"},
        "value": {"type": "number"},
        "unit": {"type": "string", "enum": ["C", "F", "Pa"]},
    },
    "required": ["sensor_id", "value", "unit"],
}


# ── Seed helper ───────────────────────────────────────────────────────────────


async def _seed_rows(rows: list[dict]) -> None:
    """Insert model rows using a fresh async engine.

    A fresh engine avoids asyncpg "Future attached to different loop" issues.
    Deferred imports ensure DATABASE_URL is set before app modules are loaded.
    """
    from app.models.model import ForgeModel  # noqa: F401 — registers ORM against Base

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


# ── Session fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def postgres_container() -> pytest.Generator[PostgresContainer, None, None]:
    with PostgresContainer("postgres:16-alpine") as pg:
        async_url = pg.get_connection_url().replace("psycopg2", "asyncpg")
        os.environ["DATABASE_URL"] = async_url
        yield pg


@pytest.fixture(scope="session")
def migrated_db(postgres_container: PostgresContainer) -> None:
    """Run Alembic migrations synchronously — must NOT be an async fixture."""
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
    command.upgrade(alembic_cfg, "head")


@pytest_asyncio.fixture(scope="session")
async def live_server(migrated_db: None) -> AsyncClient:
    """Session-scoped async client for all tests.

    session_manager.run() runs in a background asyncio.Task (not this fixture's task)
    so the anyio cancel scope enter/exit stay in one task, avoiding the cross-task
    RuntimeError that would occur if pytest-asyncio's finalizer task tried to exit it.
    """
    from app.main import app
    from app.mcp.gateway import session_manager

    stop_event = asyncio.Event()
    started_event = asyncio.Event()

    async def run_manager() -> None:
        async with session_manager.run():
            started_event.set()
            await stop_event.wait()

    manager_task: asyncio.Task[None] = asyncio.ensure_future(run_manager())
    await started_event.wait()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        timeout=30.0,
    ) as ac:
        yield ac

    stop_event.set()
    await manager_task


@pytest_asyncio.fixture(scope="session", autouse=True)
async def seeded_models(live_server: AsyncClient) -> None:
    """Seed all test models once for the entire session.

    Defined in conftest.py (not a test file) so it fires for ALL test modules
    regardless of collection order. live_server ensures the DB is up and the
    lifespan is running before we seed.
    """
    now = datetime.utcnow()
    await _seed_rows([
        {
            "id": "model-alpha",
            "name": "Org Readiness",
            "description": "Test model: Org Readiness",
            "json_schema": _SCHEMA_ORG_READINESS,
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
            "json_schema": _SCHEMA_FLEET_ASSET,
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
            "status": "draft",
            "current_version": 1,
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": "model-crud",
            "name": "Sensor Reading",
            "description": "Test model: Sensor Reading (crud + schema_only)",
            "json_schema": _SCHEMA_SENSOR,
            "system_prompt": None,
            "enabled_tool_classes": ["schema_only", "crud"],
            "metrics_config": {},
            "visibility": "public",
            "owner_sub": "test-user",
            "status": "published",
            "current_version": 1,
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": "model-scenario",
            "name": "Division Readiness",
            "description": "Test model: scenario engine (scenario + crud + schema_only)",
            "json_schema": _SCHEMA_ORG_READINESS,
            "system_prompt": None,
            "enabled_tool_classes": ["schema_only", "crud", "scenario"],
            "metrics_config": {
                "division_count": {"agg": "count"},
                "avg_personnel_pct": {"agg": "avg", "field": "personnel_pct"},
                "max_personnel_pct": {"agg": "max", "field": "personnel_pct"},
                "total_personnel_pct": {"agg": "sum", "field": "personnel_pct"},
            },
            "visibility": "public",
            "owner_sub": "test-user",
            "status": "published",
            "current_version": 1,
            "created_at": now,
            "updated_at": now,
        },
    ])


# Alias: test_health.py uses "client"
@pytest_asyncio.fixture(scope="session")
async def client(live_server: AsyncClient) -> AsyncClient:
    return live_server
