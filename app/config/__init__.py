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

    # Shared secret for the routes that spend the GitHub token or the LLM
    # (POST /github/analyze-pr, POST /smart-review, /analyze with the LLM
    # pass). Those routes answer 503 until it is set.
    api_key: str | None = None
    # Largest diff accepted from the API or fetched from GitHub, in bytes.
    max_diff_bytes: int = 2_000_000

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

    # Embeddings, similarity search and clustering of findings
    embedding_backend: str = "fastembed"  # "fastembed" or "hashing"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_cache_dir: str | None = None  # where fastembed keeps the ONNX model
    # Cosine distance under which two findings belong to the same cluster.
    cluster_distance_threshold: float = 0.15
    # Findings whose combined (embedding + TF-IDF) similarity is below this are
    # not reported as related. 0.6 keeps the same issue seen before and drops
    # different rules that merely share vocabulary, on both backends.
    similarity_min_score: float = 0.6
    # Corpus size up to which the whole corpus is re-clustered at startup.
    similarity_recluster_limit: int = 5000
    # Most findings loaded into memory at startup (newest first).
    similarity_corpus_limit: int = 20000

    # GitHub integration
    github_token: str | None = None
    github_webhook_secret: str | None = None
    github_analyze_drafts: bool = False
    github_post_comment: bool = True
    github_post_review: bool = True
    github_use_checks_api: bool = False
    github_enable_smart_review: bool = False
    # Files (most changed first) for which commit history is fetched to
    # compute the risk model's history features; 0 disables the lookups.
    github_history_max_files: int = 20
    app_public_url: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
