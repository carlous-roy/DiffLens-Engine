"""Tests for the risk scoring module."""
from app.ml.risk_scoring import score_risk, extract_features, RiskFeatures

class TestFeatureExtraction:
    def test_basic_extraction(self):
        analysis = {
            "summary": {
                "files_analyzed": 3,
                "total_findings": 10,
                "by_severity": {"info": 2, "warning": 5, "error": 2, "critical": 1},
                "by_analyzer": {"complexity": 3, "naming": 4, "bug_risk": 3},
            },
            "complexity_findings": [
                {"complexity": 5}, {"complexity": 12}, {"complexity": 3},
            ],
            "naming_findings": [],
            "bug_risk_findings": [
                {"rule_id": "PY008"},  # eval — security
                {"rule_id": "PY003"},  # mutable default
            ],
        }
        features = extract_features(analysis)
        assert features.files_changed == 3
        assert features.total_findings == 10
        assert features.critical_findings == 1
        assert features.max_complexity == 12
        assert features.avg_complexity == (5 + 12 + 3) / 3
        assert features.has_security_issue is True
        assert features.has_mutable_default is True
        assert features.naming_violations == 4

    def test_empty_analysis(self):
        analysis = {
            "summary": {
                "files_analyzed": 0, "total_findings": 0,
                "by_severity": {"info": 0, "warning": 0, "error": 0, "critical": 0},
                "by_analyzer": {"complexity": 0, "naming": 0, "bug_risk": 0},
            },
            "complexity_findings": [],
            "naming_findings": [],
            "bug_risk_findings": [],
        }
        features = extract_features(analysis)
        assert features.files_changed == 0
        assert features.max_complexity == 0
        assert features.has_security_issue is False

class TestHeuristicScoring:
    def test_low_risk(self):
        analysis = {
            "summary": {
                "files_analyzed": 1, "total_findings": 1,
                "by_severity": {"info": 1, "warning": 0, "error": 0, "critical": 0},
                "by_analyzer": {"complexity": 1, "naming": 0, "bug_risk": 0},
            },
            "complexity_findings": [{"complexity": 2}],
            "naming_findings": [],
            "bug_risk_findings": [],
        }
        risk = score_risk(analysis)
        assert risk.level == "low"
        assert risk.score < 0.3
        assert risk.model_type == "heuristic"

    def test_high_risk(self):
        analysis = {
            "summary": {
                "files_analyzed": 8, "total_findings": 20,
                "by_severity": {"info": 2, "warning": 8, "error": 5, "critical": 5},
                "by_analyzer": {"complexity": 5, "naming": 5, "bug_risk": 10},
            },
            "complexity_findings": [{"complexity": 25}],
            "naming_findings": [],
            "bug_risk_findings": [
                {"rule_id": "PY008"}, {"rule_id": "PY008"},
            ],
        }
        risk = score_risk(analysis)
        assert risk.level == "high"
        assert risk.score >= 0.6

    def test_contributing_factors_present(self):
        analysis = {
            "summary": {
                "files_analyzed": 1, "total_findings": 3,
                "by_severity": {"info": 0, "warning": 0, "error": 0, "critical": 3},
                "by_analyzer": {"complexity": 0, "naming": 0, "bug_risk": 3},
            },
            "complexity_findings": [],
            "naming_findings": [],
            "bug_risk_findings": [{"rule_id": "PY008"}],
        }
        risk = score_risk(analysis)
        assert len(risk.contributing_factors) > 0

    def test_score_in_valid_range(self):
        analysis = {
            "summary": {
                "files_analyzed": 100, "total_findings": 500,
                "by_severity": {"info": 100, "warning": 200, "error": 100, "critical": 100},
                "by_analyzer": {"complexity": 200, "naming": 100, "bug_risk": 200},
            },
            "complexity_findings": [{"complexity": 50}],
            "naming_findings": [],
            "bug_risk_findings": [{"rule_id": "PY008"} for _ in range(50)],
        }
        risk = score_risk(analysis)
        assert 0.0 <= risk.score <= 1.0

    def test_features_in_result(self):
        analysis = {
            "summary": {
                "files_analyzed": 2, "total_findings": 5,
                "by_severity": {"info": 3, "warning": 2, "error": 0, "critical": 0},
                "by_analyzer": {"complexity": 2, "naming": 2, "bug_risk": 1},
            },
            "complexity_findings": [{"complexity": 4}],
            "naming_findings": [],
            "bug_risk_findings": [],
        }
        risk = score_risk(analysis)
        assert "features" in risk.to_dict()
        assert risk.to_dict()["features"]["files_changed"] == 2
