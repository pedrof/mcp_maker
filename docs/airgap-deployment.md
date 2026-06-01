# Air-Gap Deployment Guide

FORGE is designed to run fully offline. This document lists every component that
phone-homes by default and how to replace each one.

---

## 1. Frontend fonts (Google Fonts CDN)

The frontend's `index.html` loads `Geist Mono` and `Syne` from `fonts.googleapis.com`.
On air-gapped networks this link silently fails — the app falls back to system
monospace fonts and remains fully functional.

**To serve fonts locally:**

1. Download the fonts:
   ```bash
   npx google-webfonts-helper \
     --families "Geist Mono:400,500,600" "Syne:500,600,700" \
     --output frontend/public/fonts/
   ```
2. Replace the `<link>` tags in `index.html` with local `@font-face` rules in
   `frontend/src/index.css`:
   ```css
   @font-face {
     font-family: 'Geist Mono';
     src: url('/fonts/geist-mono-v400.woff2') format('woff2');
     font-weight: 400;
   }
   /* ... repeat for other weights and Syne */
   ```
3. Remove the Google Fonts `<link>` tags from `index.html`.
4. Rebuild: `cd frontend && npm run build`

---

## 2. Anthropic API → LiteLLM proxy

The backend calls `api.anthropic.com` for the prompt-assist and test-session features.
Replace it with a local LiteLLM instance backed by any locally-served model (Ollama,
vLLM, LocalAI, etc.).

### Deploy LiteLLM on K3s

```yaml
# k8s/base/litellm.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: litellm
spec:
  replicas: 1
  selector:
    matchLabels: { app: litellm }
  template:
    metadata:
      labels: { app: litellm }
    spec:
      containers:
        - name: litellm
          image: ghcr.io/berriai/litellm:main
          args: ["--config", "/config/config.yaml", "--port", "4000"]
          volumeMounts:
            - name: config
              mountPath: /config
      volumes:
        - name: config
          configMap:
            name: litellm-config
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: litellm-config
data:
  config.yaml: |
    model_list:
      - model_name: claude-sonnet-4-20250514   # match ANTHROPIC_MODEL env var
        litellm_params:
          model: ollama/mistral                 # or any local model
          api_base: http://ollama.default.svc.cluster.local:11434
---
apiVersion: v1
kind: Service
metadata:
  name: litellm
spec:
  selector: { app: litellm }
  ports: [{ port: 4000, targetPort: 4000 }]
```

### Configure FORGE backend to use LiteLLM

Set these environment variables (Sealed Secret or K8s Secret):

```bash
ANTHROPIC_BASE_URL=http://litellm.default.svc.cluster.local:4000
ANTHROPIC_API_KEY=placeholder          # any non-empty string
ANTHROPIC_MODEL=claude-sonnet-4-20250514  # must match model_name in LiteLLM config
```

The `AsyncAnthropic` client's `base_url` parameter will point all API calls to
the LiteLLM service instead of `api.anthropic.com`. No code changes needed.

---

## 3. Container images

All images must be pulled into the local registry before air-gapping:

```bash
# Pull and push to your registry
for img in \
  postgres:16-alpine \
  python:3.12-slim \
  ghcr.io/berriai/litellm:main; do
  podman pull $img
  podman tag  $img git.shadyknollcave.io/micro/$(basename $img)
  podman push git.shadyknollcave.io/micro/$(basename $img)
done
```

Update `podman-compose.yml` and Helm `values.yaml` to reference `git.shadyknollcave.io/micro/`
images instead of the Docker Hub / GHCR originals.

---

## 4. npm packages (build time only)

npm is only needed at **build time** (CI or a connected machine), not at runtime.
The production artifact is static HTML/JS/CSS served by the backend or any web server.

**Build on a connected machine, copy the `dist/` artifact:**
```bash
cd frontend && npm run build    # produces frontend/dist/
scp -r frontend/dist/ user@air-gapped-host:/app/forge-frontend/
```

Or commit `frontend/dist/` to the repo and serve it directly.

---

## 5. Vite proxy vs. separate origin

In production, `VITE_API_BASE` is empty (default) and the frontend assumes the API
is on the same origin. If you serve the frontend from a different origin than the
backend, set:

```bash
# In frontend/.env.production
VITE_API_BASE=http://forge-api.internal:8080
```

And ensure `CORS_ORIGINS` in the backend config includes that origin.
