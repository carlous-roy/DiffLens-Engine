"""App configuration via Pydantic settings."""
from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional

class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://difflens:changeme@db:5432/difflens"

    # App
    app_env: str = "development"
    log_level: str = "INFO"
    app_name: str = "DiffLens"
    app_version: str = "1.0.0"

    # LLM
    llm_provider: str = "ollama"
    llm_base_url: str = "http://ollama:11434"
    llm_model: str = "codellama:7b"
    llm_api_key: Optional[str] = None
    llm_timeout: float = 120.0

    # ML feature flags
    ml_enable_smart_review: bool = True
    ml_enable_risk_scoring: bool = True
    ml_enable_similarity: bool = True
    ml_enable_categorization: bool = True

    # GitHub integration
    github_token: Optional[str] = None
    github_webhook_secret: Optional[str] = None
    github_analyze_drafts: bool = False
    github_post_comment: bool = True
    github_post_review: bool = True
    github_use_checks_api: bool = False
    github_enable_smart_review: bool = False
    app_public_url: Optional[str] = None

    class Config:
        env_file = ".env"
        case_sensitive = False

@lru_cache()
def get_settings() -> Settings:
    return Settings()
