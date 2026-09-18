"""Tests for the auto-categorization module."""

from app.ml.categorization import _classify_single, categorize_findings


class TestClassification:
    def test_security_eval(self):
        cat, conf, _ = _classify_single(
            "Use of eval()/exec() is a security risk.", "bug_risk", "critical"
        )
        assert cat == "security"
        assert conf > 0.8

    def test_correctness_mutable_default(self):
        cat, conf, _ = _classify_single("Mutable default argument detected.", "bug_risk", "error")
        assert cat == "correctness"
        assert conf > 0.8

    def test_correctness_equals_null(self):
        cat, conf, _ = _classify_single(
            "Calling .equals(null) always returns false.", "bug_risk", "error"
        )
        assert cat == "correctness"

    def test_style_naming(self):
        cat, conf, _ = _classify_single(
            "Function 'ProcessData' should use snake_case.", "naming", "warning"
        )
        assert cat == "style"

    def test_maintainability_global(self):
        cat, conf, _ = _classify_single(
            "Use of 'global' keyword. Global state makes code harder to test.",
            "bug_risk",
            "warning",
        )
        assert cat == "maintainability"

    def test_maintainability_todo(self):
        cat, conf, _ = _classify_single("TODO/FIXME comment found in new code.", "bug_risk", "info")
        assert cat == "maintainability"

    def test_maintainability_complexity(self):
        cat, conf, _ = _classify_single(
            "Function 'process' has cyclomatic complexity of 15.", "complexity", "error"
        )
        assert cat == "maintainability"

    def test_maintainability_nesting(self):
        cat, _, _ = _classify_single(
            "Function 'process' has a nesting depth of 5.", "complexity", "warning"
        )
        assert cat == "maintainability"

    def test_fallback_to_analyzer_default(self):
        cat, conf, _ = _classify_single(
            "Some obscure finding with no pattern match.", "complexity", "info"
        )
        assert cat == "maintainability"  # complexity analyzer default
        assert conf < 0.8


class TestCategorizationResult:
    def test_basic_categorization(self):
        findings = [
            {
                "message": "Use of eval() is a security risk.",
                "analyzer": "bug_risk",
                "severity": "critical",
            },
            {
                "message": "Function 'foo' should use snake_case.",
                "analyzer": "naming",
                "severity": "warning",
            },
            {
                "message": "Mutable default argument detected.",
                "analyzer": "bug_risk",
                "severity": "error",
            },
            {"message": "TODO comment found.", "analyzer": "bug_risk", "severity": "info"},
        ]
        result = categorize_findings(findings)
        assert result.method == "keyword"
        assert len(result.categorized) == 4
        assert result.summary["security"] >= 1
        assert result.summary["style"] >= 1
        assert result.summary["correctness"] >= 1

    def test_empty_findings(self):
        result = categorize_findings([])
        assert len(result.categorized) == 0
        assert sum(result.summary.values()) == 0

    def test_to_dict(self):
        findings = [
            {"message": "eval() usage", "analyzer": "bug_risk", "severity": "critical"},
        ]
        result = categorize_findings(findings)
        d = result.to_dict()
        assert "categorized" in d
        assert "summary" in d
        assert "method" in d
        assert d["categorized"][0]["category"] == "security"
