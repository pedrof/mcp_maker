# MCP SDK Notes

## Pinned version

```
mcp==1.26.0
```

Verified against Python 3.12 (prod target) and Python 3.13 (system default on the build host).

## Transport: Streamable HTTP

This project implements the **Streamable HTTP** transport (MCP spec rev 2025-03-26).
The older HTTP+SSE transport (`/sse`) is **not implemented** and should not be added.

### Key classes (from `mcp.server.streamable_http_manager`)

```python
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

manager = StreamableHTTPSessionManager(
    app=server,         # low-level mcp.server.Server instance
    json_response=True,
    stateless=True,     # ← NOTE: the brief says "stateless_http=True" — that param does NOT exist
                        #   in mcp==1.26.0. The correct kwarg is `stateless=True`.
)
```

`handle_request(scope, receive, send)` is the ASGI entry point; wire it into a single
FastAPI / Starlette route at `/mcp/{model_id}` (both GET and POST, per spec).

### Stateless mode

`stateless=True` is a **hard requirement** for horizontal scaling on K8s — multiple replicas
can receive any request for any model. No session state is held in-process.

### Per-model dynamic dispatch

Because multiple models are registered at runtime (not at startup), we cannot mount one
`Server` per model statically. The dispatch approach is finalized at Phase 2; see
`docs/decisions/ADR-002-mcp-gateway-dispatch.md`.

## Upgrade checklist

When upgrading `mcp`:

1. Re-verify `StreamableHTTPSessionManager.__init__` signature (especially `stateless` kwarg name).
2. Re-verify `Server` handler decorator API hasn't changed.
3. Re-run the real integration test (`test_mcp_gateway.py`) before merging.
4. Update this file with the new version + any changed params.
