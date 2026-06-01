# MCP SDK Notes

## Pinned versions

| Package | Pinned version | Role |
|---|---|---|
| `mcp` | **1.26.0** | MCP Server + StreamableHTTPSessionManager |
| `fastapi` | 0.115.12 | ASGI framework |
| `anthropic` | 0.52.0 | AI assist + test-session |
| `sqlalchemy[asyncio]` | 2.0.41 | Async ORM |
| `asyncpg` | 0.30.0 | PostgreSQL driver |
| `alembic` | 1.16.1 | Migrations |
| `pydantic` | 2.11.5 | Request/response schemas |

Verified against Python 3.12 (prod target). System Python is 3.13.

---

## Transport: Streamable HTTP only

This project implements the **Streamable HTTP** transport (MCP spec rev 2025-03-26).
The older HTTP+SSE transport (`/sse`) is **not implemented and must not be added**.

---

## Key API surface (mcp==1.26.0)

### StreamableHTTPSessionManager

```python
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

manager = StreamableHTTPSessionManager(
    app=server,
    json_response=True,
    stateless=True,    # ← correct kwarg; "stateless_http" does NOT exist in 1.26.0
)
```

`handle_request(scope, receive, send)` is the ASGI entry point. The manager is wired
as a raw ASGI app mounted at `/mcp` (not a FastAPI route — double-response otherwise).

### Stateless mode

`stateless=True` is a **hard requirement** for horizontal K8s scaling. Each request
spawns a fresh transport and task; no session state is held in-process.

### Per-request model dispatch (ADR-002)

`model_id` is read inside handlers via:
```python
server.request_context.request.path_params["model_id"]
```
The chain: `_MCPGateway` injects `model_id` into `scope["path_params"]` → transport
builds `Request(scope, receive)` → stores it as `ServerMessageMetadata(request_context=request)`
→ SDK sets it into `request_ctx` ContextVar isolated per anyio task. Safe under
concurrent requests.

**Starlette Mount does NOT strip scope["path"].** It sets `scope["root_path"] = "/mcp"`.
Extract model_id from `path[len(root_path):]`. See `app/main.py` `_MCPGateway`.

### call_tool: validate_input=False

```python
@server.call_tool(validate_input=False)
async def handle_call_tool(name, arguments):
    ...
```

`validate_input` must be `False`. When `True` (default), the SDK validates arguments
against the tool's `inputSchema` before calling the handler — this rejects invalid
data with an SDK-level MCP error whose content is empty, preventing the handler from
returning a structured `{"created": false, "errors": [...]}` tool result. Disabled so
the handler controls validation shape and error reporting.

### MCP tool inputSchema vs Anthropic input_schema

MCP `types.Tool` uses camelCase `.inputSchema`; the Anthropic messages API requires
snake_case `input_schema`. Map explicitly when building tools for the test-session:
```python
{"name": t.name, "description": t.description, "input_schema": t.inputSchema}
```

---

## Upgrade checklist

When upgrading `mcp`:

1. Re-verify `StreamableHTTPSessionManager.__init__` signature (especially `stateless`
   kwarg — it has changed name between SDK versions).
2. Re-verify `Server.call_tool(validate_input=...)` is still supported.
3. Re-verify `server.request_context.request` is still a Starlette `Request` carrying
   `path_params` (depends on `ServerMessageMetadata.request_context` chain).
4. Re-run `test_mcp_gateway.py` + `test_mcp_crud.py` + `test_mcp_scenario.py` before merging.
5. Update this file: pinned version + any changed params.

---

## Test fixture: anyio cancel scope lifetime

`session_manager.run()` creates an anyio cancel scope. anyio requires the scope to be
entered and exited in the **same Task**. pytest-asyncio's fixture finalizer runs in a
different task.

**Fix in `tests/conftest.py`:** run `session_manager` in an `asyncio.ensure_future`
background task; signal teardown via `asyncio.Event`. See ADR-002.

```python
stop_event = asyncio.Event()
manager_task = asyncio.ensure_future(run_manager())   # scope lives here
await started_event.wait()
# ... yield client ...
stop_event.set()
await manager_task   # scope exits here, same task it was entered in
```
