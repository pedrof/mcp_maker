from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from app.api.assist import router as assist_router
from app.api.health import router as health_router
from app.api.models import router as models_router
from app.api.test_session import router as test_session_router
from app.api.versions import router as versions_router
from app.auth.oidc import verify_api_key
from app.config import settings
from app.db import AsyncSessionLocal
from app.mcp.gateway import session_manager
from app.models.model import ForgeModel, ModelStatus, Visibility
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response
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

# Allow Vite dev server and production origins.
# In production, set CORS_ORIGINS env var to the actual domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(models_router)
app.include_router(versions_router)
app.include_router(assist_router)
app.include_router(test_session_router)


class _MCPGateway:
    """
    Raw ASGI app mounted at /mcp.

    Auth enforcement runs here before the MCP handler so it applies to all
    transports. FastAPI DI (Depends) does not reach raw ASGI mounts.

    - public models: always pass through (even unauthenticated).
    - protected models: require Authorization: Bearer <key>; 401 if absent/wrong.
    - unpublished/unknown models: pass through (the MCP handler returns its own error).
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return

        path: str = scope.get("path", "/")
        root_path: str = scope.get("root_path", "")
        remaining = path[len(root_path):] if path.startswith(root_path) else path
        model_id = remaining.lstrip("/").split("/")[0]

        # Bearer key check for protected models
        if model_id:
            async with AsyncSessionLocal() as db:
                model: ForgeModel | None = await db.get(ForgeModel, model_id)
            if (
                model is not None
                and model.status == ModelStatus.published
                and model.visibility == Visibility.protected
            ):
                bearer = self._extract_bearer(scope)
                if not bearer or not model.api_key_hash or not verify_api_key(bearer, model.api_key_hash):
                    deny = Response(
                        content='{"error":"invalid or missing API key"}',
                        status_code=401,
                        media_type="application/json",
                    )
                    await deny(scope, receive, send)
                    return

        scope = dict(scope)
        existing: dict[str, Any] = scope.get("path_params", {})
        scope["path_params"] = {**existing, "model_id": model_id}
        await session_manager.handle_request(scope, receive, send)

    @staticmethod
    def _extract_bearer(scope: Scope) -> str | None:
        headers = dict(scope.get("headers", []))
        auth: bytes = headers.get(b"authorization", b"")
        text = auth.decode("latin-1")
        if text.lower().startswith("bearer "):
            return text[7:].strip()
        return None


app.mount("/mcp", _MCPGateway())
