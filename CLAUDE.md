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

# Container image (build context = repo root)
make build                     # podman build -t git.shadyknollcave.io/micro/forge-backend:dev .
make push                      # build + push

# Deploy (do NOT run autonomously — affects shared homelab cluster)
helm lint deploy/helm/forge
helm template forge deploy/helm/forge | kubectl apply -f -   # dry-run preview
kustomize build deploy/kustomize/overlays/prod               # validate K3s overlay
kustomize build deploy/kustomize/overlays/openshift          # validate OCP overlay
make deploy-k3s                # kubectl apply -k + argocd app sync (run manually)
```

Running the backend manually (for E2E tests):
```bash
DATABASE_URL=postgresql+asyncpg://forge:forge@localhost:5432/forge \
PYTHONPATH=backend .venv/bin/uvicorn app.main:app --port 8080 --reload
```

## Architecture

### Request flow overview

```
Browser (React+Vite :5173 in dev / same origin in prod)
  → /api/*         FastAPI routers (authoring REST API, owner-scoped via OIDC JWT)
  → /mcp/{id}      _MCPGateway raw ASGI → bearer-key check → StreamableHTTPSessionManager → MCP Server
  → /              StaticFiles (frontend SPA, served from /app/static/ in container)
```

### Backend structure (`backend/app/`)

| Path | Purpose |
|---|---|
| `main.py` | FastAPI app, CORS, lifespan (`session_manager.run()`), routers, `_MCPGateway`, StaticFiles |
| `config.py` | `Settings` (pydantic-settings); env vars: `DATABASE_URL`, `ANTHROPIC_*`, `CORS_ORIGINS`, `OIDC_*` |
| `db.py` | Async SQLAlchemy engine + `AsyncSessionLocal` + `Base` |
| `auth/oidc.py` | `get_current_owner()` — validates Bearer JWT against Dex JWKS; dev mode returns `"anonymous"` when `OIDC_ISSUER` empty. Also `hash_api_key()` / `verify_api_key()` for per-model keys. |
| `api/deps.py` | Re-exports `get_current_owner` from `auth/oidc.py`; typed aliases `DbDep`/`OwnerDep` |
| `api/livez.py` | `GET /livez` — process-alive liveness probe (no DB). Separate from `/health` (readiness). |
| `mcp/gateway.py` | **The gateway** — one `Server` + one `StreamableHTTPSessionManager` serve all published models. `dispatch_tool_call()` extracted and reused by `/api/test/session`. |
| `tools/schema_only.py` | `get_schema`, `describe_model`, `validate_instance`, `generate_example` |
| `tools/crud.py` | `create/get/update/delete/list/query_instance` — `_load_instance()` enforces 3-predicate isolation |
| `tools/scenario.py` | Snapshot-copy what-if engine; `_compute_metrics_for_working_set()` declarative-only |
| `api/models.py` | REST CRUD + `publish` (generates bearer key for protected models) / `unpublish` lifecycle |
| `api/assist.py` | `POST /api/assist/system-prompt` — calls Anthropic server-side only |
| `api/test_session.py` | `POST /api/test/session` — Claude↔tools loop against draft models; reuses `dispatch_tool_call` |
| `clients/anthropic_client.py` | `get_anthropic_client()` dep; `ANTHROPIC_BASE_URL` → LiteLLM for air-gap |

### Auth planes (two independent, ADR-005)

**Authoring plane** (`/api/*`): OIDC JWT via `get_current_owner()` dependency.  
- Dev mode (`OIDC_ISSUER` empty): returns `"anonymous"` without validating — no Dex needed.  
- Tests override via `app.dependency_overrides[get_current_owner] = lambda: "anonymous"` (conftest session autouse).

**Data plane** (`/mcp/{id}`): per-model bearer key enforced in `_MCPGateway.__call__` before `handle_request`.  
- `public` models: unconditional pass-through.  
- `protected` models: `Authorization: Bearer <key>` required; wrong/missing → HTTP 401.  
- Key generated at first publish (`secrets.token_urlsafe(32)` → SHA-256 hex); returned once in `PublishResponse.api_key`; stable across re-publishes.

### MCP gateway dispatch (critical invariant)

`_MCPGateway` is a raw ASGI app mounted at `/mcp`. Starlette `Mount` does **not** strip `scope["path"]`; it only sets `scope["root_path"] = "/mcp"`. The class extracts `model_id` from `path[len(root_path):]` and injects it into `scope["path_params"]`.

Inside any MCP handler, `model_id` is read via:
```python
server.request_context.request.path_params["model_id"]
```
This works because the transport passes the Starlette `Request` into a per-request ContextVar isolated per anyio task. See `docs/decisions/ADR-002-mcp-gateway-dispatch.md` and `docs/mcp-notes.md`.

**`call_tool` uses `validate_input=False`** — so the handler returns structured validation errors (`{"created": false, "errors": [...]}`) rather than empty SDK-level MCP errors. See `docs/mcp-notes.md`.

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

Migrations live in `backend/migrations/versions/`. **Never use `sa.Enum` in `op.create_table()`** — asyncpg emits a duplicate `CREATE TYPE` DDL collision. Use raw SQL DDL + idempotent `DO $$ BEGIN CREATE TYPE ...; EXCEPTION WHEN duplicate_object THEN NULL; END $$` for enum types.

### Test infrastructure (important non-obvious details)

- All tests use `asyncio_default_test_loop_scope = "session"` (pyproject.toml). Tests and session-scoped fixtures share one event loop — required because `session_manager.run()` creates an anyio task group that requests spawn into.
- `live_server` in `conftest.py` runs `session_manager` in an `asyncio.ensure_future` background task and signals teardown via `asyncio.Event` — anyio cancel scopes must be entered/exited in the same task.
- `ASGITransport` does NOT trigger FastAPI's ASGI lifespan. The test fixture starts `session_manager.run()` manually.
- All `app.*` imports in test files must be **deferred inside function bodies** — module-level imports of `app.*` trigger `app.config.Settings()` during pytest collection, before testcontainers sets `DATABASE_URL`, giving the engine the wrong URL.
- Seeded test models use `owner_sub="anonymous"` (matches `get_current_owner()` dev-mode return).
- `get_current_owner` is overridden globally in conftest via `app.dependency_overrides`; auth tests that need a different owner override locally.
- Anthropic client is injectable via `app.dependency_overrides[get_anthropic_client]` in tests.

### Frontend (`frontend/`)

React 19 + TypeScript + Vite 8 + Tailwind CSS v4. State via TanStack Query v5. Key files:
- `src/api/client.ts` — thin fetch wrapper; uses `VITE_API_BASE` env var (empty = same origin / Vite proxy in dev)
- `src/api/types.ts` — TypeScript types mirroring Pydantic schemas; keep in sync manually
- `src/App.tsx` — state-based routing (no react-router routes used at top level), sidebar layout

The chat panel in `ChatPanel.tsx` POSTs to `/api/test/session` — it is **not** a browser MCP client.

In production, the SPA is served as StaticFiles from `/app/static/` inside the backend container.
In dev, Vite on `:5173` proxies `/api` and `/mcp` to the backend on `:8080`.

### Container / deploy

- **Build context = repo root**: `podman build . -f backend/Containerfile`
- Multi-stage: `python-deps` → `frontend-builder` (Node 22) → `runtime`
- OpenShift arbitrary-UID: `chgrp -R 0 /app && chmod -R g=u /app`; verified with `podman run --user 12345:0`
- Migrations run as **initContainer** (`alembic upgrade head`), not at app startup
- Liveness: `/livez` (no DB). Readiness: `/health` (SELECT 1). Startup: `/livez` with 30×2s window
- Secrets: never in images/repo; use `kubeseal` → `SealedSecret`; see `deploy/docs/secrets.md`

### Air-gap deployment

Set `ANTHROPIC_BASE_URL` to a local LiteLLM service to replace the Anthropic API. Fonts fall back to system monospace gracefully when Google Fonts is unreachable. See `docs/airgap-deployment.md`.

## Key decisions (ADRs)

- `docs/decisions/ADR-001-tech-stack.md` — why this stack; Postgres JSONB-centric, async SQLAlchemy, no Redis yet
- `docs/decisions/ADR-002-mcp-gateway-dispatch.md` — Option A (`request_context.request.path_params`), why not ContextVar or per-model Server dict; Starlette Mount path-stripping behavior
- `docs/decisions/ADR-003-scenario-engine.md` — snapshot-copy over reference-and-recompute; declarative aggregates only; no `eval()`
- `docs/decisions/ADR-004-model-versioning.md` — version written at publish time, not at edit time; slug generated at draft-create
- `docs/decisions/ADR-005-auth.md` — two auth planes (OIDC for API, bearer key for MCP); SHA-256 key hash; generate-once-if-null; rate-limiting deferred (needs Redis)
- `docs/decisions/ADR-006-deploy.md` — one-image strategy (SPA bundled into backend); build context; arbitrary-UID proof; liveness vs readiness split; migrations as initContainer; local-vs-cluster honesty note
- `docs/mcp-notes.md` — `mcp==1.26.0` pinned; `stateless=True`; `validate_input=False`; MCP→Anthropic `inputSchema` → `input_schema` mapping; upgrade checklist
