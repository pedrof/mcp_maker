# ADR-002: MCP Gateway Per-Model Dispatch

**Status:** Accepted
**Date:** 2026-05-31

## Context

The brief describes three candidate dispatch strategies for resolving `model_id` inside MCP handlers
when one Server + one StreamableHTTPSessionManager serve N models:

- **(A)** Read `server.request_context.request.path_params["model_id"]` — cleanest, if Starlette
  populates `path_params` before the scope reaches `handle_request`.
- **(B)** Set a `ContextVar` before `handle_request` and verify it survives the anyio task group hop.
- **(C)** A runtime dict of per-model Servers, handlers closing over `model_id`.

## Decision

**Option A — confirmed safe and adopted.**

Source trace (mcp==1.26.0):

1. `streamable_http.py`: the transport builds `Request(scope, receive)` and passes it as
   `ServerMessageMetadata(request_context=request)`.
2. `server.py` (line 746): `request_ctx.set(RequestContext(..., request=request_data, ...))`
   is called *inside the per-request task* spawned by `_handle_stateless_request`. Each stateless
   request gets a fresh task, so the ContextVar is isolated per request.
3. Handlers call `server.request_context.request.path_params["model_id"]` to read the model.

## Route mounting detail

`app.mount("/mcp", _MCPGateway())` with a raw ASGI `_MCPGateway` class bypasses FastAPI's response
encoding (preventing a double-response). **Starlette Mount does NOT strip `scope["path"]`; it only
sets `scope["root_path"] = "/mcp"`.** The `_MCPGateway` therefore extracts:

```python
remaining = path[len(root_path):] if path.startswith(root_path) else path
model_id = remaining.lstrip("/").split("/")[0]
```

## Test fixture: anyio cancel scope lifetime

`session_manager.run()` creates an anyio cancel scope. anyio enforces that cancel scopes are exited
in the same Task they were entered. pytest-asyncio's fixture teardown runs in a different Task.

**Fix**: Run `session_manager.run()` inside a persistent `asyncio.Task` (`asyncio.ensure_future`).
The fixture teardown signals via `asyncio.Event` and awaits the task. The cancel scope open/close
stay inside the task. See `backend/tests/conftest.py`.

## Rejected alternatives

- **Option B (ContextVar set by caller)**: viable but fragile under concurrent requests if the
  ContextVar crosses the anyio task group boundary. Not needed given Option A.
- **Option C (per-model Server dict)**: correct and heavy. Adds a lifecycle registry, AsyncExitStack
  in lifespan, and cache invalidation on publish/unpublish. Unnecessary since A works.
