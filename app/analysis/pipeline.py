"""Analysis pipeline — the main orchestrator."""

from dataclasses import asdict, dataclass, field

from app.analysis.bug_risk import detect_bug_risks
from app.analysis.complexity import analyze_complexity
from app.analysis.diff_parser import is_unified_diff, parse_diff, wrap_raw_code
from app.analysis.naming import check_java_naming, check_python_naming
from app.ml.categorization import categorize_findings
from app.ml.risk_scoring import score_risk
from app.ml.similarity import get_embedder


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


def run_analysis(diff_text: str, enable_ml: bool = True) -> AnalysisResult:
    """Run the full analysis pipeline."""
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

        added_content = fdiff.all_added_content
        if not added_content.strip():
            continue

        # -- Complexity analysis (cyclomatic complexity via Tree-sitter) --
        for cf in analyze_complexity(added_content, fdiff.path, lang):
            result.complexity_findings.append(asdict(cf))
            severity_counts[cf.severity] += 1

        # -- Naming convention checks (PEP 8 / Java style) --
        naming_fn = check_python_naming if lang == "python" else check_java_naming
        for nf in naming_fn(added_content, fdiff.path):
            result.naming_findings.append(asdict(nf))
            severity_counts[nf.severity] += 1

        # -- Bug risk pattern detection --
        added_lines = []
        for hunk in fdiff.hunks:
            added_lines.extend(hunk.added_lines)
        for bf in detect_bug_risks(added_lines, fdiff.path, lang):
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

    # -- ML-powered modules (risk scoring, categorization, similarity) --
    if enable_ml:
        _run_ml_modules(result, file_diffs)

    return result


def _run_ml_modules(result: AnalysisResult, file_diffs) -> None:
    """Run ML modules and attach results. Each is wrapped in try/except
    so a failure in one doesn't block the others."""
    all_flat = _flatten_findings(result)

    # Risk scoring — weighted heuristic over extracted diff/finding features
    try:
        risk = score_risk(result.to_dict(), file_diffs)
        result.risk_score = risk.to_dict()
    except Exception as e:
        result.risk_score = {"error": str(e)}

    # Auto-categorization — keyword rules assign security/correctness/etc.
    try:
        cat_result = categorize_findings(all_flat)
        result.categorization = cat_result.to_dict()
    except Exception as e:
        result.categorization = {"error": str(e)}

    # Similarity search — find historically similar findings
    try:
        embedder = get_embedder()
        similar_results = []
        high_sev = [f for f in all_flat if f.get("severity") in ("error", "critical")]
        for finding in high_sev[:5]:
            sim = embedder.find_similar(finding, top_k=3, threshold=0.3)
            if sim.similar_findings:
                similar_results.append(sim.to_dict())
        result.similar_findings = similar_results if similar_results else None
        # Add current findings to the corpus for future lookups
        embedder.add_findings(all_flat)
    except Exception as e:
        result.similar_findings = [{"error": str(e)}]


def _flatten_findings(result: AnalysisResult) -> list[dict]:
    """Flatten all findings into a uniform list for ML module input."""
    flat = []
    mapping = [
        (result.complexity_findings, "complexity"),
        (result.naming_findings, "naming"),
        (result.bug_risk_findings, "bug_risk"),
    ]
    for findings, analyzer in mapping:
        for f in findings:
            flat.append(
                {
                    "message": f.get("message", ""),
                    "file_path": f.get("file_path", ""),
                    "line_number": f.get("line_number"),
                    "severity": f.get("severity", "info"),
                    "analyzer": analyzer,
                    "suggestion": f.get("suggestion"),
                }
            )
    return flat
