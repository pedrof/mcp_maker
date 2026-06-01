from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://forge:forge@localhost:5432/forge"

    # Application
    app_name: str = "FORGE"
    app_version: str = "0.1.0"
    debug: bool = False

    # Auth (OIDC / Dex)
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""

    # Anthropic — server-side only, never exposed to the browser
    anthropic_api_key: str = ""
    # Optional: point to a LiteLLM proxy for air-gapped / on-prem deployments.
    # Example: ANTHROPIC_BASE_URL=http://litellm.default.svc.cluster.local:4000
    # Leave empty to use the real Anthropic API.
    anthropic_base_url: str = ""
    # Model used for assist and test-session.  Must be valid for the target endpoint.
    # anthropic==0.52.0 known good: claude-sonnet-4-20250514, claude-3-5-haiku-20241022
    anthropic_model: str = "claude-sonnet-4-20250514"

    # CORS — add production origin via env var
    # Default allows Vite dev server + same-host access
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:4173"]

    # Per-model rate limiting (requests/minute)
    rate_limit_rpm: int = 60


settings = Settings()
