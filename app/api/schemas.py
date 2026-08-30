"""Pydantic request/response models for the DiffLens API."""
from pydantic import BaseModel, Field
from typing import Optional

class AnalyzeRequest(BaseModel):
    """Request body for the /analyze endpoint."""
    diff: str = Field(..., min_length=1, description="Unified diff text to analyze.")
    source: str = Field(default="api", description="Source of the diff (api, github, gitlab).")
    enable_ml: bool = Field(default=True, description="Enable ML-powered analysis (risk scoring, categorization).")
    enable_smart_review: bool = Field(default=False, description="Enable LLM-powered smart review (requires Ollama).")

class FindingResponse(BaseModel):
    """Single finding in the analysis response."""
    analyzer: str
    file_path: str
    line_number: Optional[int] = None
    severity: str
    message: str
    suggestion: Optional[str] = None

class SummaryResponse(BaseModel):
    """Summary statistics for an analysis run."""
    files_analyzed: int
    total_findings: int
    by_severity: dict
    by_analyzer: dict

class RiskScoreResponse(BaseModel):
    """Risk assessment for a code change."""
    level: str
    score: float
    confidence: float
    contributing_factors: list[str]
    model_type: str

class AnalyzeResponse(BaseModel):
    """Response body for the /analyze endpoint."""
    run_id: Optional[str] = None
    summary: SummaryResponse
    complexity_findings: list[dict]
    naming_findings: list[dict]
    bug_risk_findings: list[dict]
    # ML fields
    risk_score: Optional[dict] = None
    categorization: Optional[dict] = None
    similar_findings: Optional[list[dict]] = None
    smart_review: Optional[dict] = None

class SmartReviewRequest(BaseModel):
    """Request for standalone smart review."""
    diff: str = Field(..., min_length=1, description="Unified diff text to review.")

class HealthResponse(BaseModel):
    """Response for the /health endpoint."""
    status: str
    version: str
    environment: str
    database: str
    llm: Optional[str] = None
    ml_features: Optional[dict] = None
