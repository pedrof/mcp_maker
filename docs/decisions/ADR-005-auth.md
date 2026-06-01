# ADR-005: Authentication Architecture

**Status:** Accepted
**Date:** 2026-05-31

## Two independent auth planes

FORGE has two independent security boundaries that share almost nothing:

### Plane 1: Authoring API (`/api/*`) — OIDC JWT

`get_current_owner()` in `app/auth/oidc.py` is a FastAPI dependency consumed via
`OwnerDep` on every REST route. It validates a Bearer JWT against the issuer's JWKS
and returns the `sub` claim.

**Dev mode** (`OIDC_ISSUER` empty): returns `"anonymous"` without validating — no Dex
needed locally. CI and integration tests override the dependency to `lambda: "anonymous"`.

**Production** (Dex): validates RS256/ES256, verifies issuer, optionally verifies audience
(`OIDC_CLIENT_ID`). JWKS is cached in-process (no TTL in Phase 8).

### Plane 2: MCP Gateway (`/mcp/{id}`) — per-model bearer key

The gateway is a raw ASGI app; FastAPI DI does not reach it. Auth is enforced in
`_MCPGateway.__call__` before `handle_request` is called:
- `public` models: pass through unconditionally.
- `protected` models: read `Authorization: Bearer <key>` from headers; return HTTP 401
  before the MCP transport if absent or wrong.
- `unpublished`/`unknown` models: pass through (MCP handler returns its own error).

Key generation returns HTTP 401 (not a JSON-RPC error body) — semantically correct for
an unauthenticated HTTP request, and simpler than surfacing auth errors through the MCP
protocol layer.

## Per-model key design

**Hash algorithm:** SHA-256 hex. High-entropy random tokens (32 bytes / 43 URL-safe
base64 chars from `secrets.token_urlsafe(32)`) do not need bcrypt's cost factor.

**Generation policy:** generate-once-if-null. The key is generated at first publish of a
`protected` model and stored as its SHA-256 hash. Re-publishing does not regenerate the
key (stable across re-publishes → existing clients keep working). To rotate: unpublish,
PATCH the model (api_key_hash field can be cleared via API in Phase 9), re-publish.

**Plaintext visibility:** the key is returned **once** in `PublishResponse.api_key` at
first publish. It is never stored in plaintext or returned again.

## Rate limiting — deferred

§9 requires rate limiting per model/key. A correct implementation needs a shared counter
(Redis or similar) so limits hold across multiple replicas (the stateless gateway is a
hard requirement). An in-process token bucket would be per-replica and misleading.
Rate limiting is explicitly deferred until a Redis dependency is added to the stack.

## No new migrations

`api_key_hash` and `visibility` columns exist in migration 0001. The `ToolClass.scenario`
and `Visibility` Python enums exist in `app/models/model.py`. Phase 8 adds no DDL.
