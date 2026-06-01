"""Injectable Anthropic async client.

Supports two modes via config:
  1. Direct Anthropic API (set ANTHROPIC_API_KEY).
  2. LiteLLM proxy (set ANTHROPIC_BASE_URL to the proxy endpoint, e.g.
     http://litellm.default.svc.cluster.local:4000 for K3s air-gapped
     deployments). ANTHROPIC_API_KEY can be any non-empty string in this mode.

LiteLLM must expose an Anthropic-compatible endpoint. Example litellm config:
  model_list:
    - model_name: claude-sonnet-4-20250514
      litellm_params:
        model: ollama/mistral  # or any backend model
        api_base: http://ollama:11434

Inject via FastAPI Depends(get_anthropic_client). Override in tests via
app.dependency_overrides[get_anthropic_client] = lambda: FakeClient().
"""

from __future__ import annotations

from typing import Any

from anthropic import AsyncAnthropic
from app.config import settings


def get_anthropic_client() -> AsyncAnthropic:
    """Return a configured AsyncAnthropic client.

    When ANTHROPIC_BASE_URL is set, the client points to a LiteLLM (or other
    Anthropic-compatible) proxy instead of the real Anthropic API.
    """
    kwargs: dict[str, Any] = {"api_key": settings.anthropic_api_key or "placeholder"}
    if settings.anthropic_base_url:
        kwargs["base_url"] = settings.anthropic_base_url
    return AsyncAnthropic(**kwargs)
