# Secrets Management

All plaintext secrets must never be committed to git. Use Sealed Secrets (kubeseal)
for the K3s homelab; the Sealed Secret is safe to commit.

## Required keys in `forge-secrets` Secret

| Key | Description |
|-----|-------------|
| `DATABASE_URL` | asyncpg DSN: `postgresql+asyncpg://forge:<pw>@<host>:5432/forge` |
| `ANTHROPIC_API_KEY` | Anthropic API key (or any string if using LiteLLM) |
| `OIDC_CLIENT_SECRET` | Dex OIDC client secret (leave empty to skip OIDC) |

## Creating a SealedSecret (kubeseal workflow)

```bash
# 1. Create plaintext Secret YAML (NEVER commit this file)
kubectl create secret generic forge-secrets \
  --from-literal=DATABASE_URL="postgresql+asyncpg://forge:CHANGEME@postgres:5432/forge" \
  --from-literal=ANTHROPIC_API_KEY="sk-ant-..." \
  --from-literal=OIDC_CLIENT_SECRET="" \
  --dry-run=client -o yaml > /tmp/forge-secrets.yaml

# 2. Seal it with the cluster's public key
kubeseal --format yaml < /tmp/forge-secrets.yaml \
  > deploy/kustomize/overlays/prod/sealed-secret.yaml

# 3. Uncomment the sealed-secret.yaml line in overlays/prod/kustomization.yaml
# 4. Commit deploy/kustomize/overlays/prod/sealed-secret.yaml (safe to commit)
# 5. Delete /tmp/forge-secrets.yaml
```

## ArgoCD Application secret (Gitea access)

ArgoCD needs a repository credential to pull from Gitea. Create it once:

```bash
kubectl create secret generic gitea-repo-creds \
  -n argocd \
  --from-literal=type=git \
  --from-literal=url=https://git.shadyknollcave.io \
  --from-literal=username=micro \
  --from-literal=password="<gitea-token>" \
  --dry-run=client -o yaml | kubeseal --format yaml \
  > deploy/argocd/gitea-repo-creds-sealed.yaml
kubectl apply -f deploy/argocd/gitea-repo-creds-sealed.yaml
```
