"""Tests for the risk scoring module: the combination formula, the trained
model path and the heuristic fallback."""

from pathlib import Path

import pytest

from app.analysis.diff_parser import parse_diff
from app.analysis.pipeline import run_analysis
from app.ml import risk_scoring
from app.ml.change_metrics import AuthorHistory, ChangeMetrics
from app.ml.risk_scoring import (
    ARTIFACT_PATH,
    SEVERITY_WEIGHTS,
    StaticFeatures,
    combine_scores,
    extract_static_features,
    level_for,
    load_risk_model,
    reset_risk_model_cache,
    risk_model_status,
    score_risk,
    static_findings_score,
)
from tests.conftest import MINIMAL_PYTHON_DIFF, SAMPLE_PYTHON_DIFF


def _analysis(critical=0, error=0, warning=0, info=0, complexities=(), rules=()):
    total = critical + error + warning + info
    return {
        "summary": {
            "files_analyzed": 1,
            "total_findings": total,
            "by_severity": {"info": info, "warning": warning, "error": error, "critical": critical},
            "by_analyzer": {"complexity": len(complexities), "naming": 0, "bug_risk": len(rules)},
        },
        "complexity_findings": [{"complexity": c, "nesting_depth": 1} for c in complexities],
        "naming_findings": [],
        "bug_risk_findings": [{"rule_id": r} for r in rules],
    }


class TestStaticFeatures:
    def test_basic_extraction(self):
        analysis = _analysis(critical=1, error=2, warning=5, info=2, complexities=(5, 12, 3))
        analysis["bug_risk_findings"] = [{"rule_id": "PY008"}, {"rule_id": "PY003"}]
        analysis["summary"]["by_analyzer"] = {"complexity": 3, "naming": 4, "bug_risk": 3}
        features = extract_static_features(analysis)
        assert features.total_findings == 10
        assert features.critical_findings == 1
        assert features.max_complexity == 12
        assert features.avg_complexity == round((5 + 12 + 3) / 3, 3)
        assert features.has_security_issue is True
        assert features.has_mutable_default is True
        assert features.naming_violations == 4

    def test_nesting_findings_do_not_count_as_complexity(self):
        analysis = _analysis(complexities=(4,))
        analysis["complexity_findings"].append(
            {"metric": "nesting_depth", "complexity": 4, "nesting_depth": 5}
        )
        features = extract_static_features(analysis)
        assert features.max_complexity == 4
        assert features.max_nesting_depth == 5

    def test_empty_analysis(self):
        features = extract_static_features(_analysis())
        assert features.total_findings == 0
        assert features.has_security_issue is False


class TestCombinationFormula:
    """The documented formula: noisy-OR over findings, then over the two sources."""

    def test_no_findings_scores_zero(self):
        assert static_findings_score(StaticFeatures()) == 0.0

    def test_single_critical_equals_its_weight(self):
        assert static_findings_score(StaticFeatures(critical_findings=1)) == pytest.approx(
            SEVERITY_WEIGHTS["critical"]
        )

    def test_findings_combine_as_noisy_or(self):
        s = static_findings_score(StaticFeatures(critical_findings=2, error_findings=1))
        expected = 1 - (1 - 0.30) ** 2 * (1 - 0.12)
        assert s == pytest.approx(expected, abs=1e-4)

    def test_info_findings_do_not_count(self):
        assert static_findings_score(StaticFeatures(info_findings=50)) == 0.0

    def test_static_score_saturates(self):
        ten = static_findings_score(StaticFeatures(critical_findings=10))
        twenty = static_findings_score(StaticFeatures(critical_findings=20))
        assert ten < twenty < 1.0
        assert twenty - ten < ten  # diminishing returns

    def test_combine_is_noisy_or(self):
        assert combine_scores(0.2, 0.5) == pytest.approx(1 - 0.8 * 0.5)
        assert combine_scores(0.0, 0.0) == 0.0
        assert combine_scores(1.0, 0.0) == 1.0
        assert combine_scores(0.3, 0.0) == pytest.approx(0.3)

    def test_combine_clamps_inputs(self):
        assert combine_scores(1.7, -0.2) == 1.0

    def test_levels(self):
        assert level_for(0.0) == "low"
        assert level_for(0.2999) == "low"
        assert level_for(0.3) == "medium"
        assert level_for(0.5999) == "medium"
        assert level_for(0.6) == "high"
        assert level_for(1.0) == "high"


@pytest.mark.skipif(not ARTIFACT_PATH.exists(), reason="trained artefact not present")
class TestTrainedModelPath:
    def setup_method(self):
        reset_risk_model_cache()

    def test_artifact_loads_and_reports_status(self):
        assert load_risk_model() is not None
        status = risk_model_status()
        assert status["model_type"] == "gradient_boosting"
        assert status["loaded"] is True
        assert set(status["variants"]) == {"full", "diff_only"}
        assert status["variants"]["full"]["metrics"]["roc_auc"] > 0.7

    def test_artifact_is_under_five_megabytes(self):
        assert ARTIFACT_PATH.stat().st_size < 5 * 1024 * 1024

    def test_diff_only_variant_without_history(self):
        result = run_analysis(MINIMAL_PYTHON_DIFF, enable_ml=False)
        risk = score_risk(result.to_dict(), parse_diff(MINIMAL_PYTHON_DIFF))
        assert risk.model_type == "gradient_boosting"
        assert risk.model_version.endswith("/diff_only")
        assert 0.0 <= risk.model_probability <= 1.0
        assert risk.static_score == 0.0  # two info-level complexity findings only
        assert risk.score == pytest.approx(risk.model_probability)
        assert risk.level == "low"
        assert risk.warnings and "diff-only" in risk.warnings[0]
        assert risk.combination["method"] == "noisy_or"
        assert risk.combination["attribution_method"] == "baseline_ablation"

    def test_full_variant_with_history(self):
        result = run_analysis(MINIMAL_PYTHON_DIFF, enable_ml=False)
        history = AuthorHistory(ndev=2.0, age=30.0, nuc=10.0, aexp=50.0)
        risk = score_risk(result.to_dict(), parse_diff(MINIMAL_PYTHON_DIFF), history=history)
        assert risk.model_version.endswith("/full")
        assert risk.warnings == []
        assert risk.features["aexp"] == 50.0
        assert {a["feature"] for a in risk.attributions} <= {
            "la",
            "ld",
            "nf",
            "nd",
            "ns",
            "ent",
            "age",
            "nuc",
            "aexp",
        }

    def test_attributions_are_ranked_and_complete(self):
        result = run_analysis(SAMPLE_PYTHON_DIFF, enable_ml=False)
        risk = score_risk(result.to_dict(), parse_diff(SAMPLE_PYTHON_DIFF))
        assert 1 <= len(risk.attributions) <= 5
        magnitudes = [abs(a["contribution"]) for a in risk.attributions]
        assert magnitudes == sorted(magnitudes, reverse=True)
        for attr in risk.attributions:
            assert set(attr) == {"feature", "label", "value", "baseline", "contribution"}

    def test_static_findings_raise_the_score(self):
        clean = run_analysis(MINIMAL_PYTHON_DIFF, enable_ml=False)
        buggy = run_analysis(SAMPLE_PYTHON_DIFF, enable_ml=False)
        clean_risk = score_risk(clean.to_dict(), parse_diff(MINIMAL_PYTHON_DIFF))
        buggy_risk = score_risk(buggy.to_dict(), parse_diff(SAMPLE_PYTHON_DIFF))
        assert buggy_risk.static_score > 0.4
        assert buggy_risk.score > clean_risk.score
        assert buggy_risk.level in ("medium", "high")
        assert buggy_risk.score == pytest.approx(
            combine_scores(buggy_risk.model_probability, buggy_risk.static_score), abs=1e-4
        )

    def test_larger_change_gets_higher_model_probability(self):
        small = ChangeMetrics(la=5, ld=0, nf=1, nd=1, ns=1, ent=0.0)
        large = ChangeMetrics(la=900, ld=300, nf=12, nd=6, ns=3, ent=2.5)
        model = load_risk_model()
        p_small, _, _ = model.predict(small)
        p_large, _, _ = model.predict(large)
        assert p_large > p_small

    def test_many_critical_findings_give_high(self):
        analysis = _analysis(critical=5, error=5, complexities=(25,), rules=["PY008"] * 5)
        risk = score_risk(analysis, parse_diff(SAMPLE_PYTHON_DIFF))
        assert risk.level == "high"
        assert risk.score >= 0.6


class TestHeuristicFallback:
    def setup_method(self):
        reset_risk_model_cache()

    def teardown_method(self):
        reset_risk_model_cache()

    def test_missing_artifact_falls_back_and_logs(self, tmp_path, monkeypatch, caplog):
        monkeypatch.setattr(risk_scoring, "ARTIFACT_PATH", tmp_path / "missing.joblib")
        with caplog.at_level("ERROR", logger="app.ml.risk_scoring"):
            assert load_risk_model(tmp_path / "missing.joblib") is None
        assert "heuristic fallback" in caplog.text
        assert risk_model_status()["model_type"] == "heuristic"

        analysis = _analysis(critical=1, complexities=(3,), rules=["PY008"])
        risk = score_risk(analysis, parse_diff(SAMPLE_PYTHON_DIFF))
        assert risk.model_type == "heuristic"
        assert risk.model_probability is None
        assert risk.static_score == pytest.approx(0.30, abs=1e-4)
        assert risk.attributions == []
        assert "heuristic fallback" in risk.warnings[0]
        assert risk.level == "medium"

    def test_corrupt_artifact_falls_back(self, tmp_path, caplog):
        bad = tmp_path / "risk_model.joblib"
        bad.write_bytes(b"not a joblib file")
        with caplog.at_level("ERROR", logger="app.ml.risk_scoring"):
            assert load_risk_model(bad) is None
        assert "could not be loaded" in caplog.text

    def test_wrong_format_version_rejected(self, tmp_path):
        import joblib

        path = tmp_path / "risk_model.joblib"
        joblib.dump({"format_version": 1, "models": {}}, path)
        with pytest.raises(ValueError, match="Unsupported artefact format"):
            risk_scoring.RiskModel.load(path)

    def test_heuristic_scores_large_changes(self, tmp_path):
        load_risk_model(tmp_path / "missing.joblib")
        big = "diff --git a/x.py b/x.py\nnew file mode 100644\n--- /dev/null\n+++ b/x.py\n"
        big += "@@ -0,0 +1,300 @@\n" + "".join(f"+x{i} = {i}\n" for i in range(300))
        result = run_analysis(big, enable_ml=False)
        risk = score_risk(result.to_dict(), parse_diff(big))
        assert risk.model_type == "heuristic"
        assert "Large change (300 lines added)" in risk.contributing_factors
        assert risk.score > 0


def test_artifact_path_is_inside_the_package():
    assert Path(ARTIFACT_PATH).parent.name == "artifacts"
    assert Path(ARTIFACT_PATH).parent.parent.name == "ml"
