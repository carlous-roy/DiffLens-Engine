"""Core REST API routes for DiffLens."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db import get_db
from app.db.models import AnalysisRun, AnalysisFinding, SeverityLevel
from app.api.schemas import (
    AnalyzeRequest, AnalyzeResponse, HealthResponse,
    SummaryResponse, SmartReviewRequest,
)
from app.analysis.pipeline import run_analysis
from app.ml.smart_review import smart_review
from app.ml.llm_provider import get_llm_provider
from app.config import get_settings

router = APIRouter()
settings = get_settings()

@router.get("/health", response_model=HealthResponse)
async def health_check(db: Session = Depends(get_db)):
    """Health check endpoint — verifies database and LLM connectivity."""
    db_status = "healthy"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_status = "unhealthy"

    # Check LLM availability
    llm_status = "disabled"
    if settings.ml_enable_smart_review:
        provider = get_llm_provider()
        try:
            available = await provider.is_available()
            llm_status = "connected" if available else "not_reachable"
        except Exception:
            llm_status = "error"

    ml_features = {
        "smart_review": settings.ml_enable_smart_review,
        "risk_scoring": settings.ml_enable_risk_scoring,
        "similarity": settings.ml_enable_similarity,
        "categorization": settings.ml_enable_categorization,
    }

    return HealthResponse(
        status="healthy" if db_status == "healthy" else "degraded",
        version=settings.app_version,
        environment=settings.app_env,
        database=db_status,
        llm=llm_status,
        ml_features=ml_features,
    )

@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_diff(request: AnalyzeRequest, db: Session = Depends(get_db)):
    """Analyze a unified diff for code quality issues."""
    try:
        result = run_analysis(request.diff, enable_ml=request.enable_ml)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Analysis failed: {str(e)}")

    # Persist the run
    run = AnalysisRun(source=request.source, summary=result.summary)
    db.add(run)
    db.flush()

    # Persist individual findings
    all_findings = []
    for f in result.complexity_findings:
        all_findings.append(AnalysisFinding(
            run_id=run.id, analyzer="complexity",
            file_path=f["file_path"], line_number=f.get("line_number"),
            severity=SeverityLevel(f["severity"].lower()),
            message=f["message"], suggestion=f.get("suggestion"),
            metadata_={"function_name": f.get("function_name"), "complexity": f.get("complexity")},
        ))
    for f in result.naming_findings:
        all_findings.append(AnalysisFinding(
            run_id=run.id, analyzer="naming",
            file_path=f["file_path"], line_number=f.get("line_number"),
            severity=SeverityLevel(f["severity"].lower()),
            message=f["message"], suggestion=f.get("suggestion"),
            metadata_={"name": f.get("name"), "kind": f.get("kind")},
        ))
    for f in result.bug_risk_findings:
        all_findings.append(AnalysisFinding(
            run_id=run.id, analyzer="bug_risk",
            file_path=f["file_path"], line_number=f.get("line_number"),
            severity=SeverityLevel(f["severity"].lower()),
            message=f["message"], suggestion=f.get("suggestion"),
            metadata_={"rule_id": f.get("rule_id"), "matched_text": f.get("matched_text")},
        ))

    db.add_all(all_findings)
    db.commit()
    db.refresh(run)

    # Smart review (async, optional)
    review_result = None
    if request.enable_smart_review and settings.ml_enable_smart_review:
        try:
            review_result = await smart_review(
                request.diff,
                static_findings=result.to_dict(),
            )
            review_result = review_result.to_dict()
        except Exception as e:
            review_result = {"error": str(e), "llm_available": False}

    return AnalyzeResponse(
        run_id=str(run.id),
        summary=SummaryResponse(**result.summary),
        complexity_findings=result.complexity_findings,
        naming_findings=result.naming_findings,
        bug_risk_findings=result.bug_risk_findings,
        risk_score=result.risk_score,
        categorization=result.categorization,
        similar_findings=result.similar_findings,
        smart_review=review_result,
    )

@router.post("/smart-review")
async def standalone_smart_review(request: SmartReviewRequest):
    """Standalone LLM-powered smart review endpoint."""
    if not settings.ml_enable_smart_review:
        raise HTTPException(status_code=503, detail="Smart review is disabled.")

    try:
        result = await smart_review(request.diff)
        return result.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Smart review failed: {str(e)}")

@router.get("/ml/status")
async def ml_status():
    """Check the status of all ML features."""
    provider = get_llm_provider()
    llm_available = False
    llm_models = []

    try:
        llm_available = await provider.is_available()
        if llm_available:
            llm_models = await provider.list_models()
    except Exception:
        pass

    return {
        "llm": {
            "provider": provider.provider,
            "model": provider.model,
            "base_url": provider.base_url,
            "available": llm_available,
            "installed_models": llm_models,
        },
        "features": {
            "smart_review": settings.ml_enable_smart_review,
            "risk_scoring": settings.ml_enable_risk_scoring,
            "similarity": settings.ml_enable_similarity,
            "categorization": settings.ml_enable_categorization,
        },
    }

@router.get("/runs")
def list_runs(limit: int = 20, db: Session = Depends(get_db)):
    """List recent analysis runs."""
    runs = (
        db.query(AnalysisRun)
        .order_by(AnalysisRun.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": str(r.id),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "source": r.source,
            "status": r.status,
            "summary": r.summary,
        }
        for r in runs
    ]

@router.get("/runs/{run_id}")
def get_run(run_id: str, db: Session = Depends(get_db)):
    """Get details of a specific analysis run including all findings."""
    run = db.query(AnalysisRun).filter(AnalysisRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
    return {
        "id": str(run.id),
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "source": run.source,
        "status": run.status,
        "summary": run.summary,
        "findings": [
            {
                "id": str(f.id),
                "analyzer": f.analyzer,
                "file_path": f.file_path,
                "line_number": f.line_number,
                "severity": f.severity.value if f.severity else None,
                "message": f.message,
                "suggestion": f.suggestion,
                "metadata": f.metadata_,
            }
            for f in run.findings
        ],
    }
