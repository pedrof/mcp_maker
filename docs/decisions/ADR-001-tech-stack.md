# ADR-001: Core Technology Stack

**Status:** Accepted
**Date:** 2026-05-31

## Context

FORGE needs a backend that hosts both a REST authoring API and a dynamic multi-tenant MCP gateway,
with Postgres for persistence, and must run on K3s (and be OpenShift-portable).

## Decisions

| Concern | Choice | Rationale |
|---|---|---|
| Python runtime | 3.12 | Stable, LTS-adjacent; 3.13 is system default but prod pinned to 3.12 for consistency |
| Web framework | FastAPI 0.115.x | Async-native, Pydantic v2 native, great ASGI middleware story |
| ASGI server | Uvicorn (dev) / Gunicorn+Uvicorn (prod) | Standard; supports multiple workers |
| MCP transport | Streamable HTTP only | Spec-current as of 2025-03-26; SSE transport is deprecated |
| MCP SDK | `mcp==1.26.0` (low-level `Server` + `StreamableHTTPSessionManager`) | FastMCP is too opinionated; low-level gives per-model dynamic dispatch |
| Database | PostgreSQL 16 via SQLAlchemy 2.x async + asyncpg | JSONB for schema/instance data; async aligns with FastAPI |
| Migrations | Alembic (async env.py) | Standard; async env avoids sync-engine gotchas |
| Schema validation | `jsonschema` (Draft 2020-12) | Spec-compliant; fastjsonschema can be layered if perf warrants |
| Auth | OIDC (Dex-compatible) for UI; per-model bearer API key for MCP endpoints | Separates authoring identity from client identity |
| Container runtime | Podman (rootless) | Homelab policy; image-compatible with OCI standard |

## Postgres as the single source of truth

All published model configs (schema, system prompt, tool classes) live in Postgres.
The gateway loads them per-request (with an in-process LRU cache). No separate config store.

## Rejected alternatives

- **FastMCP**: convenient but doesn't support per-request dynamic model dispatch without patching.
- **SQLite**: no JSONB, no concurrent async writes across replicas.
- **Redis for session**: stateless mode makes server-side session unnecessary.
