# FORGE Architecture

## System overview

```
┌─────────────────────────────────────────────────────────┐
│  Browser (React SPA)                                    │
│    GET /          ← StaticFiles (SPA)                  │
│    /api/*         ← Authoring REST API (OIDC JWT)      │
│    /mcp/{id}      ← MCP gateway (bearer key optional)  │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP
                         ▼
┌─────────────────────────────────────────────────────────┐
│  Backend (FastAPI + uvicorn, Python 3.12)               │
│                                                         │
│  /livez   process-alive (no DB)   ← liveness           │
│  /health  SELECT 1                ← readiness          │
│                                                         │
│  /api/models/*      ModelRouter  ─ owner-scoped CRUD   │
│  /api/assist/*      AssistRouter ─ Anthropic (server)  │
│  /api/test/*        TestRouter   ─ ephemeral session   │
│                                                         │
│  /mcp/{id}  _MCPGateway (raw ASGI)                     │
│    ├── bearer-key check (protected models)              │
│    └── StreamableHTTPSessionManager (stateless=True)   │
│         └── MCP Server (one, serves all published)     │
│              ├── list_tools / call_tool                 │
│              ├── list_resources / read_resource         │
│              └── list_prompts / get_prompt              │
│                                                         │
│  Auth:  get_current_owner() → OIDC JWT → Dex           │
│         (dev mode: returns "anonymous" if OIDC_ISSUER   │
│          is empty)                                      │
└────────────────────────┬────────────────────────────────┘
                         │ asyncpg
                         ▼
┌─────────────────────────────────────────────────────────┐
│  PostgreSQL 16                                          │
│    models          JSON Schema + system prompt          │
│    model_versions  frozen config snapshots at publish   │
│    instances       JSONB data (GIN indexed, soft delete)│
│    scenarios       snapshot-copy what-if engine         │
└─────────────────────────────────────────────────────────┘
                         │ API call
                         ▼
              ┌──────────────────┐
              │  Anthropic API   │
              │  (or LiteLLM     │
              │   for air-gap)   │
              └──────────────────┘
```

## Data flow: publish + MCP request

```
Author (browser)
  1. POST /api/models/{id}/publish
     → validates JSON Schema
     → INSERT model_versions (frozen config snapshot)
     → models.status = "published"
     → returns PublishResponse (+ api_key if protected)

LLM client (any MCP client)
  2. POST /mcp/{id}   (initialize / list_tools / call_tool)
     → _MCPGateway: extract model_id from scope["root_path"]
     → for protected models: verify Bearer token
     → StreamableHTTPSessionManager spawns a stateless task
     → MCP Server reads model_id from request_context.request.path_params
     → _load_published_model(model_id) → DB lookup
     → dispatch_tool_call(name, args, model, db) → tool handler
     → JSON response
```

## Tool dispatch chain

```
call_tool(name, args)
  ├── schema_only tools?  → so_tools.call_schema_only_tool()
  ├── crud tools?         → crud_tools.*()  (via _load_instance isolation guard)
  └── scenario tools?     → scenario_tools.*()  (via _load_scenario isolation guard)
```

Both `_load_instance(model_id, id, db)` and `_load_scenario(model_id, id, db)` enforce
three predicates (id + model_id + alive/status) to prevent cross-tenant leaks.

## Model lifecycle

```
[draft]  ──publish──►  [published]  ──unpublish──►  [unpublished]
   ▲                                                      │
   │               re-publish (new version)               │
   └──────────────────────────────────────────────────────┘
```

At publish: current config is snaphotted to `model_versions`; `current_version` increments.
No cache — gateway loads per-request, so publish/unpublish is instantly live.

## Scenario engine

```
create_scenario(name)
  └── snapshots live instances into base_snapshot JSONB

apply_change(scenario_id, op, data)
  └── appends to changes JSONB log (never touches live instances)

compute_metrics(scenario_id)
  └── _apply_changes_to_snapshot(base_snapshot, changes)  [in-memory only]
      └── _compute_metrics_for_working_set(working_set, metrics_config)
          └── declarative: count|sum|avg|min|max — no eval()

compare_to_baseline()  →  per-metric {baseline, current, delta}
reset_scenario()        →  clear changes log
```

## Deploy topology (K3s homelab)

```
Git push → Gitea → ArgoCD (watches deploy/kustomize/overlays/prod)
  → kustomize build
  → kubectl apply (namespace: forge)
  → Deployment (2 replicas, HPA optional)
      initContainer: alembic upgrade head
      container:     forge-backend:tag (port 8080)
  → Service (ClusterIP :8080)
  → Ingress (Cilium, Let's Encrypt TLS)
      forge.shadyknollcave.io → forge-svc:8080
```

Secrets: `forge-secrets` SealedSecret (DATABASE_URL, ANTHROPIC_API_KEY, OIDC_CLIENT_SECRET).
See `deploy/docs/secrets.md`.
