"""Analysis pipeline: parse the diff, run the analyzers, then the scoring modules."""

from dataclasses import asdict, dataclass, field

import numpy as np

from app.analysis.bug_risk import detect_bug_risks
from app.analysis.complexity import analyze_complexity
from app.analysis.diff_parser import is_unified_diff, parse_diff, wrap_raw_code
from app.analysis.naming import check_java_naming, check_python_naming
from app.config import get_settings
from app.ml.categorization import categorize_findings
from app.ml.change_metrics import AuthorHistory
from app.ml.risk_scoring import score_risk
from app.ml.similarity import analyze_findings, get_finding_index


@dataclass
class AnalysisResult:
    """Complete output from an analysis run."""

    files_analyzed: int = 0
    total_findings: int = 0
    complexity_findings: list[dict] = field(default_factory=list)
    naming_findings: list[dict] = field(default_factory=list)
    bug_risk_findings: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    risk_score: dict | None = None
    categorization: dict | None = None
    similar_findings: list[dict] | None = None
    # Not serialised: what persistence needs to store the similarity results.
    finding_vectors: np.ndarray | None = field(default=None, repr=False)
    finding_cluster_ids: list[int] | None = field(default=None, repr=False)
    embedding_model: str | None = field(default=None, repr=False)

    def all_findings(self) -> list[dict]:
        """Every finding with its analyzer tag, in a fixed order.

        The order matters: categorization, embeddings and cluster ids are
        stored positionally against this list.
        """
        flat = []
        for findings, analyzer in (
            (self.complexity_findings, "complexity"),
            (self.naming_findings, "naming"),
            (self.bug_risk_findings, "bug_risk"),
        ):
            for f in findings:
                flat.append({**f, "analyzer": analyzer})
        return flat

    def to_dict(self) -> dict:
        return {
            "files_analyzed": self.files_analyzed,
            "total_findings": self.total_findings,
            "complexity_findings": self.complexity_findings,
            "naming_findings": self.naming_findings,
            "bug_risk_findings": self.bug_risk_findings,
            "summary": self.summary,
            "risk_score": self.risk_score,
            "categorization": self.categorization,
            "similar_findings": self.similar_findings,
        }


def run_analysis(
    diff_text: str,
    enable_ml: bool = True,
    history: AuthorHistory | None = None,
) -> AnalysisResult:
    """Run the full analysis pipeline.

    `history` carries repository-history metrics for the change when the
    caller (the GitHub flow) could measure them; the risk model uses its
    diff-only variant otherwise.
    """
    # If the user pasted raw code instead of a diff, wrap it automatically.
    # This way the Analyze page works for both use cases.
    if diff_text.strip() and not is_unified_diff(diff_text):
        diff_text = wrap_raw_code(diff_text)

    file_diffs = parse_diff(diff_text)
    result = AnalysisResult(files_analyzed=len(file_diffs))
    severity_counts = {"info": 0, "warning": 0, "error": 0, "critical": 0}

    for fdiff in file_diffs:
        lang = fdiff.language
        if lang not in ("python", "java"):
            continue

        # The analyzers see the hunks as they read after the change (context
        # plus added lines) and report only on added lines, with line numbers
        # translated back to the new file through the hunk headers.
        view = fdiff.post_image()
        if not view.has_changes or not fdiff.all_added_content.strip():
            continue

        # -- Complexity analysis (cyclomatic complexity and nesting depth) --
        for cf in analyze_complexity(view.text, fdiff.path, lang, view):
            result.complexity_findings.append(asdict(cf))
            severity_counts[cf.severity] += 1

        # -- Naming convention checks (PEP 8 / Java style) --
        naming_fn = check_python_naming if lang == "python" else check_java_naming
        for nf in naming_fn(view.text, fdiff.path, view):
            result.naming_findings.append(asdict(nf))
            severity_counts[nf.severity] += 1

        # -- Bug risk rules over code (comments and strings masked) --
        for bf in detect_bug_risks(view.text, fdiff.path, lang, view):
            result.bug_risk_findings.append(asdict(bf))
            severity_counts[bf.severity] += 1

    result.total_findings = sum(severity_counts.values())
    result.summary = {
        "files_analyzed": result.files_analyzed,
        "total_findings": result.total_findings,
        "by_severity": severity_counts,
        "by_analyzer": {
            "complexity": len(result.complexity_findings),
            "naming": len(result.naming_findings),
            "bug_risk": len(result.bug_risk_findings),
        },
    }

    # -- Risk scoring, categorization, similarity --
    if enable_ml:
        _run_ml_modules(result, file_diffs, history)

    return result


def _run_ml_modules(result: AnalysisResult, file_diffs, history: AuthorHistory | None) -> None:
    """Run the scoring modules that are enabled in settings and attach their
    results. Each is wrapped in try/except so a failure in one does not block
    the others."""
    settings = get_settings()
    all_flat = result.all_findings()

    # Risk scoring: calibrated model probability combined with the findings
    if settings.ml_enable_risk_scoring:
        try:
            risk = score_risk(result.to_dict(), file_diffs, history=history)
            result.risk_score = risk.to_dict()
        except Exception as e:
            result.risk_score = {"error": str(e)}

    # Categorization: keyword rules assign security/correctness/etc.
    if settings.ml_enable_categorization:
        try:
            cat_result = categorize_findings(all_flat)
            result.categorization = cat_result.to_dict()
        except Exception as e:
            result.categorization = {"error": str(e)}

    if not settings.ml_enable_similarity or not all_flat:
        return

    # Similarity search and clustering: related past findings, repeat clusters
    try:
        index = get_finding_index()
        analysis = analyze_findings(all_flat, index)
        originals = _finding_refs(result)
        seen_before = 0
        for original, sim_result in zip(originals, analysis.results, strict=True):
            original["cluster_id"] = sim_result.cluster_id
            original["times_seen_before"] = sim_result.times_seen_before
            if sim_result.times_seen_before:
                seen_before += 1
        result.summary["findings_seen_before"] = seen_before
        with_hits = [r.to_dict() for r in analysis.results if r.similar_findings]
        result.similar_findings = with_hits or None
        result.finding_vectors = analysis.vectors
        result.finding_cluster_ids = analysis.cluster_ids
        result.embedding_model = index.model.name
    except Exception as e:
        result.similar_findings = [{"error": str(e)}]


def _finding_refs(result: AnalysisResult) -> list[dict]:
    """The original finding dicts in `all_findings()` order, for writing back."""
    return [*result.complexity_findings, *result.naming_findings, *result.bug_risk_findings]
