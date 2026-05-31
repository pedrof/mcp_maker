from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from app.api.health import router as health_router
from app.api.models import router as models_router
from app.api.versions import router as versions_router
from app.config import settings
from app.mcp.gateway import session_manager
from fastapi import FastAPI
from starlette.types import Receive, Scope, Send

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("FORGE starting", version=settings.app_version)
    # session_manager.run() must wrap the entire app lifetime — it sets up
    # the anyio task group that stateless requests spawn into.
    async with session_manager.run():
        yield
    logger.info("FORGE shutting down")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(models_router)
app.include_router(versions_router)


class _MCPGateway:
    """
    Raw ASGI app mounted at /mcp.  FastAPI strips the /mcp prefix before
    handing off to this app, so scope["path"] = "/{model_id}".
    We inject path_params so Request.path_params["model_id"] works inside
    the MCP handler chain (server.request_context.request.path_params).
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return
        # Starlette Mount does NOT strip scope["path"]; it sets root_path = mount prefix.
        # Extract model_id from the remaining path after the mount prefix.
        path: str = scope.get("path", "/")
        root_path: str = scope.get("root_path", "")
        remaining = path[len(root_path):] if path.startswith(root_path) else path
        model_id = remaining.lstrip("/").split("/")[0]
        # Inject path_params so server.request_context.request.path_params["model_id"] works
        scope = dict(scope)
        existing: dict[str, Any] = scope.get("path_params", {})
        scope["path_params"] = {**existing, "model_id": model_id}
        await session_manager.handle_request(scope, receive, send)


app.mount("/mcp", _MCPGateway())
