"""
Test fixtures for FORGE backend integration tests.

Architecture:
  - postgres_container (sync, session) — starts a real Postgres via testcontainers
  - migrated_db (sync, session) — runs Alembic migrations once
  - live_server (async, session) — starts app with session_manager lifecycle
  - client (async, session) — alias for live_server for test_health.py

Key design decisions:
  1. Alembic's env.py calls asyncio.run() — migrated_db MUST be sync (no outer event loop).
  2. ASGITransport does NOT trigger the ASGI lifespan, so session_manager.run() must
     be started manually.
  3. anyio cancel scopes MUST be entered and exited in the same Task. pytest-asyncio
     finalizes fixtures in a separate finalizer task. We therefore run session_manager
     in a persistent background asyncio.Task and signal it via an asyncio.Event.
     The cancel scope opens and closes inside that background task, never crossing
     the task boundary.
  4. All tests use asyncio_default_test_loop_scope = "session" (pyproject.toml) so
     the DB connections, the background task, and the test code all share one event loop.
"""

from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from testcontainers.postgres import PostgresContainer


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
    """
    Session-scoped async client for all tests.

    session_manager.run() creates an anyio task group (cancel scope). anyio
    enforces that cancel scopes are exited in the SAME task they were entered.
    pytest-asyncio's fixture teardown runs in a different task → RuntimeError.

    Fix: run the session_manager inside a dedicated asyncio.Task. That task
    both enters AND exits the cancel scope; the fixture teardown only signals
    it via asyncio.Event, never crossing the task boundary.
    """
    # Deferred import: DATABASE_URL must be set before app modules are imported
    from app.main import app
    from app.mcp.gateway import session_manager

    stop_event = asyncio.Event()
    started_event = asyncio.Event()

    async def run_manager() -> None:
        async with session_manager.run():
            started_event.set()
            await stop_event.wait()
        # run() has exited cleanly here — cancel scope enter/exit stay in this task

    manager_task: asyncio.Task[None] = asyncio.ensure_future(run_manager())
    await started_event.wait()  # Ensure task group is live before yielding

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        timeout=30.0,
    ) as ac:
        yield ac

    stop_event.set()
    await manager_task


# Alias so test_health.py (which uses "client") works unchanged
@pytest_asyncio.fixture(scope="session")
async def client(live_server: AsyncClient) -> AsyncClient:
    return live_server
