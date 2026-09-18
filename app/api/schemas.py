"""Pydantic request/response models for the DiffLens API."""

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    """Request body for the /analyze endpoint."""

    diff: str = Field(..., min_length=1, description="Unified diff text to analyze.")
    source: str = Field(default="api", description="Source of the diff (api, github, gitlab).")
    enable_ml: bool = Field(
        default=True, description="Run risk scoring, categorization and similarity search."
    )
    enable_smart_review: bool = Field(
        default=False,
        description="Run the optional LLM review pass (requires a configured provider).",
    )


class SummaryResponse(BaseModel):
    """Summary statistics for an analysis run."""

    files_analyzed: int
    total_findings: int
    by_severity: dict
    by_analyzer: dict


class AnalyzeResponse(BaseModel):
    """Response body for the /analyze endpoint."""

    run_id: str | None = None
    summary: SummaryResponse
    complexity_findings: list[dict]
    naming_findings: list[dict]
    bug_risk_findings: list[dict]
    # ML fields
    risk_score: dict | None = None
    categorization: dict | None = None
    similar_findings: list[dict] | None = None
    smart_review: dict | None = None


class SmartReviewRequest(BaseModel):
    """Request for standalone smart review."""

    diff: str = Field(..., min_length=1, description="Unified diff text to review.")


class HealthResponse(BaseModel):
    """Response for the /health endpoint."""

    status: str
    version: str
    environment: str
    database: str
    llm: str | None = None
    ml_features: dict | None = None
    risk_model: str | None = None
