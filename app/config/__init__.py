"""App configuration via Pydantic settings."""

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# The env file is read from the working directory. Set DIFFLENS_ENV_FILE to
# an empty string to ignore it (the test suite does this to stay hermetic).
_ENV_FILE = os.environ.get("DIFFLENS_ENV_FILE", ".env") or None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        case_sensitive=False,
        extra="ignore",
    )

    # Database. Defaults to a local SQLite file so the app runs from a clean
    # clone; docker-compose and any real deployment set DATABASE_URL to Postgres.
    database_url: str = "sqlite:///./difflens.db"

    # App
    app_env: str = "development"
    log_level: str = "INFO"
    app_name: str = "DiffLens"
    app_version: str = "1.1.0"

    # Frontend / browser clients
    dashboard_url: str = "http://localhost:3000"
    # Comma-separated list of origins allowed to call the API.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # LLM
    llm_provider: str = "ollama"
    llm_base_url: str = "http://ollama:11434"
    llm_model: str = "codellama:7b"
    llm_api_key: str | None = None
    llm_timeout: float = 120.0

    # ML feature flags
    ml_enable_smart_review: bool = True
    ml_enable_risk_scoring: bool = True
    ml_enable_similarity: bool = True
    ml_enable_categorization: bool = True

    # GitHub integration
    github_token: str | None = None
    github_webhook_secret: str | None = None
    github_analyze_drafts: bool = False
    github_post_comment: bool = True
    github_post_review: bool = True
    github_use_checks_api: bool = False
    github_enable_smart_review: bool = False
    app_public_url: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
