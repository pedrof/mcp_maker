import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("postgres:16-alpine") as pg:
        # Replace psycopg2 driver with asyncpg for the app; keep sync URL for Alembic
        async_url = pg.get_connection_url().replace("psycopg2", "asyncpg")
        os.environ["DATABASE_URL"] = async_url
        yield pg


@pytest.fixture(scope="session")
def migrated_db(postgres_container: PostgresContainer) -> None:
    """Run Alembic migrations synchronously against the test Postgres.

    Alembic's env.py calls asyncio.run() internally. This must be a sync
    fixture so there is no outer event loop when asyncio.run() fires.
    """
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
    command.upgrade(alembic_cfg, "head")


@pytest_asyncio.fixture(scope="session")
async def client(migrated_db: None) -> AsyncClient:
    # Import after DATABASE_URL env var is set so Settings picks it up
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac  # type: ignore[misc]
