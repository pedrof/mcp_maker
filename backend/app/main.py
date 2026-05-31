from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from app.api.health import router as health_router
from app.config import settings
from fastapi import FastAPI

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("FORGE starting", version=settings.app_version)
    yield
    logger.info("FORGE shutting down")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

app.include_router(health_router)
