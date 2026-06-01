# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**FORGE** — A platform where a user defines a JSON Schema data model, authors a system prompt with AI assistance, and publishes a live **Model Context Protocol (MCP) Streamable HTTP** endpoint at `/mcp/{model-id}`. Transport is Streamable HTTP only (`stateless=True`); the old SSE transport is not implemented and must not be added.

## Commands

All backend commands run from the project root (where `pyproject.toml` lives). The venv lives at `.venv/`.

```bash
# First-time setup
make venv                      # python3.12 -m venv .venv && pip install -e ".[dev]"

# Local dev stack (Postgres + backend via podman-compose)
make dev                       # podman-compose up --build
make stop

# Backend tests (real Postgres via testcontainers — no local DB needed)
make test                      # cd backend && pytest -v --cov=app
# Single test file
cd backend && PYTHONPATH=. ../.venv/bin/pytest tests/test_mcp_gateway.py -v
# Single test
cd backend && PYTHONPATH=. ../.venv/bin/pytest tests/test_mcp_crud.py::test_create_then_get -v

# Backend lint + type check
make lint                      # ruff check + mypy
make lint-fix                  # ruff check --fix
PYTHONPATH=backend .venv/bin/mypy backend/app

# Alembic migrations
make migrate                   # upgrade head (requires DB reachable)
make migrate-new msg="add foo" # generate autogenerate revision

# Frontend
cd frontend && npm install
cd frontend && npm run dev     # Vite dev server on :5173 (proxies /api + /mcp to :8080)
cd frontend && npm run build   # tsc -b && vite build
cd frontend && npx playwright test   # E2E (requires backend on :8080 + vite on :5173)
```

Running the backend manually (for E2E tests):
```bash
DATABASE_URL=postgresql+asyncpg://forge:forge@localhost:5432/forge \
PYTHONPATH=backend .venv/bin/uvicorn app.main:app --port 8080 --reload
```

## Architecture

### Request flow overview

```
Browser (React+Vite :5173)
  → /api/*         FastAPI routers (authoring REST API)
  → /mcp/{id}      _MCPGateway raw ASGI → StreamableHTTPSessionManager → MCP Server
```

### Backend structure (`backend/app/`)

| Path | Purpose |
|---|---|
| `main.py` | FastAPI app, CORS middleware, lifespan (session_manager.run()), mounts routers and `_MCPGateway` |
| `config.py` | `Settings` (pydantic-settings); reads env vars including `DATABASE_URL`, `ANTHROPIC_*`, `CORS_ORIGINS` |
| `db.py` | Async SQLAlchemy engine + `AsyncSessionLocal` session factory + `Base` |
| `mcp/gateway.py` | **The gateway** — one `Server` + one `StreamableHTTPSessionManager` serve all published models. `dispatch_tool_call()` is extracted here and reused by `/api/test/session`. |
| `tools/schema_only.py` | `get_schema`, `describe_model`, `validate_instance`, `generate_example` |
| `tools/crud.py` | `create/get/update/delete/list/query_instance` with `_load_instance()` isolation guard |
| `tools/scenario.py` | Snapshot-copy what-if engine; `_compute_metrics_for_working_set()` is declarative-only |
| `api/models.py` | REST CRUD + `publish` / `unpublish` lifecycle |
| `api/assist.py` | `POST /api/assist/system-prompt` — calls Anthropic; never exposes key to browser |
| `api/test_session.py` | `POST /api/test/session` — Claude↔tools loop against draft models; reuses `dispatch_tool_call` |
| `api/deps.py` | `get_current_owner()` stub (returns `"anonymous"` until Phase 8 OIDC); `DbDep`/`OwnerDep` type aliases |
| `clients/anthropic_client.py` | `get_anthropic_client()` FastAPI dependency; set `ANTHROPIC_BASE_URL` to redirect to LiteLLM |

### MCP gateway dispatch (critical invariant)

`_MCPGateway` is a raw ASGI app mounted at `/mcp`. Starlette `Mount` does **not** strip `scope["path"]`; it only sets `scope["root_path"] = "/mcp"`. The class extracts `model_id` from the path suffix and injects it into `scope["path_params"]`.

Inside any MCP handler, `model_id` is read via:
```python
server.request_context.request.path_params["model_id"]
```
This works because `mcp.server.streamable_http.py` passes the Starlette `Request` as `ServerMessageMetadata(request_context=request)` and the SDK sets it into a ContextVar isolated per anyio task (each stateless request spawns a fresh task). See `docs/decisions/ADR-002-mcp-gateway-dispatch.md`.

### Tool gating

`dispatch_tool_call()` in `gateway.py` checks `model.enabled_tool_classes` before dispatching. Three classes: `schema_only`, `crud`, `scenario`. Each tool definition is generated from the model's JSON Schema so LLM clients get model-specific `inputSchema` values.

### Model lifecycle (status machine)

```
draft  →  published   (POST /api/models/{id}/publish — validates schema, snapshots to model_versions)
published  →  unpublished   (POST /api/models/{id}/unpublish)
unpublished  →  published   (re-publish; increments version)
```
The gateway only checks `status == "published"`. No cache — per-request DB load means publish/unpublish is instantly live. Published models cannot be PATCH-edited; unpublish first.

### Database

Four tables: `models`, `model_versions`, `instances`, `scenarios`. Notable:
- `instances.data` is JSONB with a GIN index; `deleted_at IS NULL` = alive (soft delete).
- `scenarios.base_snapshot` is a JSONB copy of live instance data at `create_scenario` time — scenarios never touch live rows.
- `metrics_config` format: `{"metric_name": {"agg": "count|sum|avg|min|max", "field": "field_name"}}` — declarative only, no `eval()`.

### Alembic migrations

Migrations live in `backend/migrations/versions/`. **Never use `sa.Enum` in `op.create_table()`** — asyncpg emits a duplicate `CREATE TYPE` DDL collision. Use raw SQL DDL + `DO $$ BEGIN CREATE TYPE ...; EXCEPTION WHEN duplicate_object THEN NULL; END $$` for enum types.

### Test infrastructure (important non-obvious details)

- All tests use `asyncio_default_test_loop_scope = "session"` (pyproject.toml). Tests and session-scoped fixtures share one event loop — required because `session_manager.run()` creates an anyio task group that requests spawn into.
- `live_server` in `conftest.py` runs `session_manager` in an `asyncio.ensure_future` background task and signals teardown via `asyncio.Event` — anyio cancel scopes must be entered/exited in the same task.
- `ASGITransport` does NOT trigger FastAPI's ASGI lifespan. The test fixture starts `session_manager.run()` manually.
- All `app.*` imports in test files must be **deferred inside function bodies** — module-level imports of `app.*` trigger `app.config.Settings()` during pytest collection, before testcontainers sets `DATABASE_URL`, giving the engine the wrong URL.
- Seeded test models use `owner_sub="anonymous"` (matches `get_current_owner()` stub).
- Anthropic client is injectable via `app.dependency_overrides[get_anthropic_client]` in tests.

### Frontend (`frontend/`)

React 18 + TypeScript + Vite + Tailwind CSS v4. State via TanStack Query v5. Key files:
- `src/api/client.ts` — thin fetch wrapper; uses `VITE_API_BASE` env var (empty = same origin / Vite proxy in dev)
- `src/api/types.ts` — TypeScript types mirroring Pydantic schemas; keep in sync manually
- `src/App.tsx` — state-based routing (no react-router routes used yet), sidebar layout

The chat panel in `ChatPanel.tsx` POSTs to `/api/test/session` — it is not a browser MCP client.

### Air-gap deployment

Set `ANTHROPIC_BASE_URL` to a local LiteLLM service to replace the Anthropic API. Fonts fall back to system monospace gracefully when Google Fonts is unreachable. See `docs/airgap-deployment.md`.

## Key decisions (ADRs)

- `docs/decisions/ADR-001-tech-stack.md` — why this stack
- `docs/decisions/ADR-002-mcp-gateway-dispatch.md` — Option A (request_context.request.path_params), why not ContextVar or per-model Server dict
- `docs/decisions/ADR-003-scenario-engine.md` — snapshot-copy over reference-and-recompute; declarative aggregates only
- `docs/decisions/ADR-004-model-versioning.md` — version written at publish time, not at edit time
- `docs/mcp-notes.md` — `mcp==1.26.0` pinned, `stateless=True` param name (not `stateless_http`), upgrade checklist
