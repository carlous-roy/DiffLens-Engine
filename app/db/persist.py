"""Persist an analysis run, its findings and their embeddings."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.analysis.pipeline import AnalysisResult
from app.db.models import AnalysisFinding, AnalysisRun, GitHubPR, SeverityLevel
from app.ml.similarity import get_finding_index

logger = logging.getLogger(__name__)

_METADATA_KEYS = {
    "complexity": ("function_name", "complexity", "nesting_depth", "metric"),
    "naming": ("name", "kind"),
    "bug_risk": ("rule_id", "matched_text"),
}


def persist_run(
    db: Session,
    result: AnalysisResult,
    source: str,
    github: dict | None = None,
) -> AnalysisRun:
    """Store the run and findings; register the findings in the similarity index.

    `github` carries owner, repo, pr_number, head_sha and action when the run
    came from a pull request.
    """
    run = AnalysisRun(source=source, summary=result.summary, risk=result.risk_score)
    db.add(run)
    db.flush()

    if github:
        db.add(
            GitHubPR(
                run_id=run.id,
                owner=github["owner"],
                repo=github["repo"],
                pr_number=github["pr_number"],
                head_sha=github["head_sha"],
                action=github.get("action", "opened"),
                pr_url=f"https://github.com/{github['owner']}/{github['repo']}/pull/"
                f"{github['pr_number']}",
            )
        )

    flat = result.all_findings()
    categories = _categories(result, len(flat))
    vectors = result.finding_vectors
    cluster_ids = result.finding_cluster_ids
    model_name = result.embedding_model
    rows: list[AnalysisFinding] = []
    for i, f in enumerate(flat):
        analyzer = f["analyzer"]
        rows.append(
            AnalysisFinding(
                run_id=run.id,
                analyzer=analyzer,
                file_path=f["file_path"],
                line_number=f.get("line_number"),
                severity=SeverityLevel(f["severity"].lower()),
                message=f["message"],
                suggestion=f.get("suggestion"),
                metadata_={k: f.get(k) for k in _METADATA_KEYS.get(analyzer, ())},
                category=categories[i],
                embedding=vectors[i] if vectors is not None else None,
                embedding_model=model_name if vectors is not None else None,
                cluster_id=cluster_ids[i] if cluster_ids is not None else None,
            )
        )
    db.add_all(rows)
    db.commit()
    db.refresh(run)

    if vectors is not None and cluster_ids is not None and len(rows):
        try:
            get_finding_index().add_run(
                str(run.id), flat, vectors, cluster_ids, [str(r.id) for r in rows]
            )
        except Exception:
            logger.exception("Could not add run %s to the similarity index.", run.id)
    return run


def _categories(result: AnalysisResult, count: int) -> list[str | None]:
    cat = result.categorization or {}
    categorized = cat.get("categorized") if isinstance(cat, dict) else None
    if not categorized or len(categorized) != count:
        return [None] * count
    return [c.get("category") for c in categorized]
