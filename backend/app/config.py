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

    # Anthropic
    anthropic_api_key: str = ""

    # Per-model rate limiting (requests/minute)
    rate_limit_rpm: int = 60


settings = Settings()
