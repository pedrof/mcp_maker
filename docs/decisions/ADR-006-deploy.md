# ADR-006: Deployment Architecture

**Status:** Accepted
**Date:** 2026-05-31

## Frontend serving: backend StaticFiles (one-image strategy)

The frontend SPA (`frontend/dist/`) is bundled into the backend image at build time
and served by FastAPI's `StaticFiles` mount at `/`. This keeps the deployment to a single
image, which is the simplest path for the air-gapped K3s homelab (one image to mirror,
not two). The trade-off vs. a separate nginx-static image: the backend process serves
static assets, which is acceptable given the traffic profile (internal homelab tool).

## Build context

`podman build` uses the **repo root** as build context (`-f backend/Containerfile`).
This allows the multi-stage Containerfile to copy `pyproject.toml` (repo root),
`backend/app/`, and `frontend/` in separate COPY statements.

## OpenShift arbitrary-UID compatibility

`chgrp -R 0 /app && chmod -R g=u /app` in the runtime stage ensures any UID assigned
by OpenShift's restricted-v2 SCC (random UID in group 0) can write to `/app`.
The `containerSecurityContext` drops all capabilities and sets `runAsNonRoot: true`.
Locally verified: `podman run --user 12345:0` → `/livez` returns 200.

## Liveness vs readiness probes

- **Readiness** (`/health`): does `SELECT 1` against Postgres. Gates traffic — a
  healthy DB means the replica is ready to serve.
- **Liveness** (`/livez`): process-alive check, no DB. Prevents a transient DB blip
  from triggering a crashloop restart of all replicas simultaneously.
- **Startup** (`/livez`): allows up to 60 s for cold start (uvicorn + lifespan).

## Migrations

`alembic upgrade head` runs as an **initContainer** on each deploy, before the app
container starts. With multiple replicas, the first pod's initContainer runs the
migration; subsequent pods' initContainers find no pending migrations and exit fast.
This is safe because Alembic's migration lock (advisory lock on Postgres) prevents
concurrent migration runs from conflicting.

**Rejected alternative**: baking migration into the app's lifespan startup —
N replicas racing migrations with no coordination.

## Rate limiting deferred

Deferred from Phase 8. An in-process limiter would be per-replica and misleading in
a stateless multi-replica deployment. Correct implementation requires a shared counter
(Redis or similar). ADR pending when Redis is added.

## Local validation vs cluster verification

**Statically validated locally:**
- `podman build` succeeds (multi-stage, Node + Python builders).
- Arbitrary-UID test: `podman run --user 12345:0` → `/livez` 200.
- `helm lint` + `helm template` produce valid YAML.
- `kustomize build` on both overlays (prod + openshift) produces valid YAML.

**Requires a live cluster to verify:**
- Ingress TLS (cert-manager + Let's Encrypt HTTP-01).
- ArgoCD GitOps sync round-trip.
- OpenShift SCC admission (`oc adm policy add-scc-to-user restricted-v2 -z forge`).
- Multi-replica load-balanced MCP sessions.

ArgoCD is wired to the Gitea repo; push manifests → sync is triggered automatically.
The `make deploy-k3s` target applies + syncs but should be run by the operator, not
autonomously by Claude Code (shared cluster state).

## Digest pinning

Base images (`python:3.12-slim`, `node:22-slim`) can be pinned by digest now.
The application image (`forge-backend:latest`) is pinned to a digest only after
push — the digest is unknown pre-build. The Kustomize `images` stanza accepts
`newDigest: sha256:...` for post-push pinning.
