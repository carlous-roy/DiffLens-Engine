"""Tests for the analysis pipeline."""

from app.analysis.pipeline import run_analysis
from tests.conftest import MINIMAL_PYTHON_DIFF, SAMPLE_JAVA_DIFF, SAMPLE_PYTHON_DIFF


def test_pipeline_python_diff():
    """End-to-end pipeline test with ML enabled."""
    result = run_analysis(SAMPLE_PYTHON_DIFF, enable_ml=True)

    assert result.files_analyzed == 1
    assert result.total_findings > 0

    # Static analysis still works
    assert len(result.naming_findings) > 0
    assert len(result.bug_risk_findings) > 0
    assert len(result.complexity_findings) > 0

    # ML results
    assert result.risk_score is not None
    assert "level" in result.risk_score
    assert result.risk_score["level"] in ("low", "medium", "high")

    assert result.categorization is not None
    assert "categorized" in result.categorization
    assert "summary" in result.categorization

    # Risk should be medium or high for this buggy code
    assert result.risk_score["level"] in ("medium", "high")


def test_pipeline_java_diff():
    result = run_analysis(SAMPLE_JAVA_DIFF, enable_ml=True)
    assert result.risk_score is not None
    assert result.categorization is not None


def test_pipeline_clean_code():
    result = run_analysis(MINIMAL_PYTHON_DIFF, enable_ml=True)
    assert result.risk_score is not None
    assert result.risk_score["level"] == "low"


def test_pipeline_ml_disabled():
    """ML modules should not run when disabled."""
    result = run_analysis(SAMPLE_PYTHON_DIFF, enable_ml=False)
    assert result.risk_score is None
    assert result.categorization is None
    assert result.similar_findings is None

    # Static analysis still works
    assert result.total_findings > 0


def test_pipeline_categorization_covers_all_findings():
    """All findings should be categorized."""
    result = run_analysis(SAMPLE_PYTHON_DIFF, enable_ml=True)
    total_static = (
        len(result.complexity_findings)
        + len(result.naming_findings)
        + len(result.bug_risk_findings)
    )
    categorized_count = len(result.categorization["categorized"])
    assert categorized_count == total_static


def test_pipeline_risk_has_factors():
    result = run_analysis(SAMPLE_PYTHON_DIFF, enable_ml=True)
    assert len(result.risk_score["contributing_factors"]) > 0


def test_pipeline_empty_diff():
    result = run_analysis("", enable_ml=True)
    assert result.files_analyzed == 0
    assert result.total_findings == 0


def test_pipeline_unsupported_language():
    diff = """diff --git a/style.css b/style.css
--- /dev/null
+++ b/style.css
@@ -0,0 +1,3 @@
+body {
+    color: red;
+}
"""
    result = run_analysis(diff, enable_ml=True)
    # The file is parsed, but CSS has no analyzer, so nothing is reported.
    assert result.files_analyzed == 1
    assert result.total_findings == 0
    assert result.complexity_findings == []
    assert result.naming_findings == []
    assert result.bug_risk_findings == []
