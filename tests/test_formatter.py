"""Tests for GitHub output formatter."""

from app.analysis.pipeline import AnalysisResult
from app.github.formatter import (
    findings_to_annotations,
    findings_to_review_comments,
    format_summary_comment,
    risk_level_to_conclusion,
    risk_level_to_status_state,
)


def _make_analysis(
    complexity=None,
    naming=None,
    bug_risk=None,
    risk_level="low",
    risk_score=0.2,
) -> AnalysisResult:
    """Helper to build an AnalysisResult for testing."""
    result = AnalysisResult()
    result.complexity_findings = complexity or []
    result.naming_findings = naming or []
    result.bug_risk_findings = bug_risk or []
    result.total_findings = (
        len(result.complexity_findings)
        + len(result.naming_findings)
        + len(result.bug_risk_findings)
    )
    result.summary = {
        "files_analyzed": 2,
        "total_findings": result.total_findings,
        "by_severity": {"critical": 0, "error": 1, "warning": 1, "info": 0},
        "by_analyzer": {
            "complexity": len(result.complexity_findings),
            "naming": len(result.naming_findings),
            "bug_risk": len(result.bug_risk_findings),
        },
    }
    result.risk_score = {
        "level": risk_level,
        "score": risk_score,
        "contributing_factors": ["test factor"],
    }
    result.categorization = None
    return result


SAMPLE_FINDINGS = [
    {
        "file_path": "src/auth.py",
        "line_number": 42,
        "severity": "error",
        "message": "High cyclomatic complexity (15)",
        "suggestion": "Consider breaking into smaller functions",
        "function_name": "process_auth",
        "complexity": 15,
    },
    {
        "file_path": "src/utils.py",
        "line_number": 10,
        "severity": "warning",
        "message": "Function name 'DoSomething' should be snake_case",
        "suggestion": "Rename to 'do_something'",
        "name": "DoSomething",
        "kind": "function",
    },
]


class TestFormatSummaryComment:
    def test_contains_header(self):
        analysis = _make_analysis(complexity=[SAMPLE_FINDINGS[0]])
        comment = format_summary_comment(analysis)
        assert "DiffLens Code Review" in comment

    def test_contains_risk_level(self):
        analysis = _make_analysis(complexity=[SAMPLE_FINDINGS[0]], risk_level="high")
        comment = format_summary_comment(analysis)
        assert "HIGH" in comment

    def test_contains_findings_count(self):
        analysis = _make_analysis(
            complexity=[SAMPLE_FINDINGS[0]],
            naming=[SAMPLE_FINDINGS[1]],
        )
        comment = format_summary_comment(analysis)
        assert "2" in comment

    def test_contains_severity_breakdown(self):
        analysis = _make_analysis(complexity=[SAMPLE_FINDINGS[0]])
        comment = format_summary_comment(analysis)
        assert "Error" in comment

    def test_includes_smart_review(self):
        analysis = _make_analysis()
        sr = {
            "comments": [{"file": "f.py", "line": 1, "comment": "looks good"}],
            "overall_summary": "Clean code.",
        }
        comment = format_summary_comment(analysis, smart_review=sr)
        assert "AI Review" in comment
        assert "Clean code." in comment


class TestAnnotations:
    def test_converts_findings_to_annotations(self):
        analysis = _make_analysis(complexity=[SAMPLE_FINDINGS[0]])
        annotations = findings_to_annotations(analysis)
        assert len(annotations) == 1
        assert annotations[0]["path"] == "src/auth.py"
        assert annotations[0]["start_line"] == 42
        assert annotations[0]["annotation_level"] == "failure"  # error → failure

    def test_skips_findings_without_line_number(self):
        finding = {**SAMPLE_FINDINGS[0], "line_number": None}
        analysis = _make_analysis(complexity=[finding])
        annotations = findings_to_annotations(analysis)
        assert len(annotations) == 0


class TestReviewComments:
    def test_only_high_severity(self):
        analysis = _make_analysis(
            complexity=[SAMPLE_FINDINGS[0]],  # error
            naming=[SAMPLE_FINDINGS[1]],  # warning
        )
        comments = findings_to_review_comments(analysis)
        # Only error findings should be included
        assert len(comments) == 1
        assert comments[0]["path"] == "src/auth.py"

    def test_includes_suggestion(self):
        analysis = _make_analysis(complexity=[SAMPLE_FINDINGS[0]])
        comments = findings_to_review_comments(analysis)
        assert "Suggestion" in comments[0]["body"]


class TestRiskMapping:
    def test_status_states(self):
        assert risk_level_to_status_state("low") == "success"
        assert risk_level_to_status_state("medium") == "success"
        assert risk_level_to_status_state("high") == "failure"
        assert risk_level_to_status_state("critical") == "failure"

    def test_conclusions(self):
        assert risk_level_to_conclusion("low") == "success"
        assert risk_level_to_conclusion("medium") == "neutral"
        assert risk_level_to_conclusion("high") == "failure"
