"""OIDC JWT validation for the authoring API.

When OIDC_ISSUER is empty (dev/CI), returns the ANONYMOUS_OWNER constant without
touching a real Dex instance. Swap to real validation by setting OIDC_ISSUER.

Validation chain:
  1. Fetch JWKS from {issuer}/.well-known/openid-configuration → jwks_uri.
  2. Decode + verify the Bearer JWT using RS256 (or whatever alg the key specifies).
  3. Return jwt["sub"].

JWKS is fetched synchronously on first call and then cached in-process. Key rotation
is handled by clearing the cache (or restarting); a production deployment should add
a short TTL. For Phase 8 the simple in-process cache is sufficient.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import httpx
from app.config import settings
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)

# In-process JWKS cache (list of key dicts from JWKS endpoint)
_jwks_cache: list[dict[str, Any]] | None = None


def _fetch_jwks(issuer: str) -> list[dict[str, Any]]:
    global _jwks_cache
    if _jwks_cache is not None:
        return _jwks_cache
    oidc_config_url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
    with httpx.Client(timeout=10) as client:
        oidc_cfg = client.get(oidc_config_url).raise_for_status().json()
        jwks = client.get(oidc_cfg["jwks_uri"]).raise_for_status().json()
    _jwks_cache = jwks.get("keys", [])
    logger.info("JWKS fetched from %s (%d keys)", oidc_cfg["jwks_uri"], len(_jwks_cache))
    return _jwks_cache


def _decode_token(token: str, issuer: str) -> str:
    """Validate the JWT and return the sub claim."""
    keys = _fetch_jwks(issuer)
    try:
        claims = jwt.decode(
            token,
            keys,
            algorithms=["RS256", "ES256"],
            audience=settings.oidc_client_id or None,
            issuer=issuer,
            options={"verify_aud": bool(settings.oidc_client_id)},
        )
        return str(claims["sub"])
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}") from exc


def get_current_owner(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),  # noqa: B008
) -> str:
    """FastAPI dependency: return owner sub from Bearer JWT.

    Dev mode (OIDC_ISSUER empty): returns 'anonymous' without validating.
    Production: validates RS256/ES256 JWT against Dex JWKS, returns sub.
    """
    if not settings.oidc_issuer:
        # Dev / CI — no Dex configured. Accept any bearer or no token.
        return "anonymous"

    if credentials is None:
        raise HTTPException(status_code=401, detail="Authorization header required")

    return _decode_token(credentials.credentials, settings.oidc_issuer)


def hash_api_key(key: str) -> str:
    """SHA-256 hex digest used for api_key_hash storage."""
    return hashlib.sha256(key.encode()).hexdigest()


def verify_api_key(plaintext: str, stored_hash: str) -> bool:
    return hash_api_key(plaintext) == stored_hash
