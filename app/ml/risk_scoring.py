"""Code Change Risk Scoring — feature extraction and risk prediction."""

import logging
from dataclasses import asdict, dataclass

import numpy as np

logger = logging.getLogger(__name__)

try:
    import joblib
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.preprocessing import StandardScaler

    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False


@dataclass
class RiskFeatures:
    """Feature vector extracted from a diff and its analysis."""

    files_changed: int = 0
    total_additions: int = 0
    total_deletions: int = 0
    max_file_additions: int = 0
    total_findings: int = 0
    critical_findings: int = 0
    error_findings: int = 0
    warning_findings: int = 0
    max_complexity: int = 0
    avg_complexity: float = 0.0
    has_security_issue: bool = False
    has_mutable_default: bool = False
    naming_violations: int = 0
    bug_risk_count: int = 0
    churn_ratio: float = 0.0  # deletions / (additions + 1)

    def to_vector(self) -> list[float]:
        """Convert to numeric feature vector for ML model."""
        return [
            self.files_changed,
            self.total_additions,
            self.total_deletions,
            self.max_file_additions,
            self.total_findings,
            self.critical_findings,
            self.error_findings,
            self.warning_findings,
            self.max_complexity,
            self.avg_complexity,
            float(self.has_security_issue),
            float(self.has_mutable_default),
            self.naming_violations,
            self.bug_risk_count,
            self.churn_ratio,
        ]


FEATURE_NAMES = [
    "files_changed",
    "total_additions",
    "total_deletions",
    "max_file_additions",
    "total_findings",
    "critical_findings",
    "error_findings",
    "warning_findings",
    "max_complexity",
    "avg_complexity",
    "has_security_issue",
    "has_mutable_default",
    "naming_violations",
    "bug_risk_count",
    "churn_ratio",
]


@dataclass
class RiskScore:
    """Risk assessment result for a code change."""

    level: str  # low, medium, high
    score: float  # 0.0 to 1.0
    confidence: float  # 0.0 to 1.0
    contributing_factors: list[str]
    features: dict
    model_type: str  # "heuristic" or "trained"

    def to_dict(self) -> dict:
        return asdict(self)


def extract_features(analysis_result: dict, file_diffs: list | None = None) -> RiskFeatures:
    """Extract ML features from an analysis result and optional raw diffs."""
    features = RiskFeatures()

    summary = analysis_result.get("summary", {})
    features.files_changed = summary.get("files_analyzed", 0)
    features.total_findings = summary.get("total_findings", 0)

    by_severity = summary.get("by_severity", {})
    features.critical_findings = by_severity.get("critical", 0)
    features.error_findings = by_severity.get("error", 0)
    features.warning_findings = by_severity.get("warning", 0)

    by_analyzer = summary.get("by_analyzer", {})
    features.naming_violations = by_analyzer.get("naming", 0)
    features.bug_risk_count = by_analyzer.get("bug_risk", 0)

    # Complexity features
    complexities = []
    for cf in analysis_result.get("complexity_findings", []):
        c = cf.get("complexity", 0)
        if c:
            complexities.append(c)
    if complexities:
        features.max_complexity = max(complexities)
        features.avg_complexity = sum(complexities) / len(complexities)

    # Security and mutable default detection
    for bf in analysis_result.get("bug_risk_findings", []):
        rule_id = bf.get("rule_id", "")
        if rule_id in ("PY008", "JV001"):  # eval() or .equals(null)
            features.has_security_issue = True
        if rule_id == "PY003":  # mutable default
            features.has_mutable_default = True

    # Line count features from diffs
    if file_diffs:
        total_add = 0
        total_del = 0
        max_add = 0
        for fd in file_diffs:
            file_add = sum(len(h.added_lines) for h in fd.hunks)
            file_del = sum(len(h.removed_lines) for h in fd.hunks)
            total_add += file_add
            total_del += file_del
            max_add = max(max_add, file_add)
        features.total_additions = total_add
        features.total_deletions = total_del
        features.max_file_additions = max_add
        features.churn_ratio = total_del / (total_add + 1)

    return features


def _heuristic_score(features: RiskFeatures) -> RiskScore:
    """Heuristic-based risk scoring used before a trained model is available."""
    score = 0.0
    factors = []

    # Critical findings are strong risk signals
    if features.critical_findings > 0:
        score += 0.3 * min(features.critical_findings, 3)
        factors.append(f"{features.critical_findings} critical finding(s) (e.g., eval() usage)")

    # Error-level findings
    if features.error_findings > 0:
        score += 0.15 * min(features.error_findings, 4)
        factors.append(f"{features.error_findings} error-level finding(s)")

    # High complexity
    if features.max_complexity > 15:
        score += 0.2
        factors.append(f"Very high complexity ({features.max_complexity})")
    elif features.max_complexity > 10:
        score += 0.1
        factors.append(f"High complexity ({features.max_complexity})")

    # Large changes are riskier
    if features.total_additions > 200:
        score += 0.15
        factors.append(f"Large change ({features.total_additions} lines added)")
    elif features.total_additions > 100:
        score += 0.08
        factors.append(f"Moderate change size ({features.total_additions} lines added)")

    # Many files changed
    if features.files_changed > 5:
        score += 0.1
        factors.append(f"Many files changed ({features.files_changed})")

    # High churn ratio suggests refactoring (moderate risk)
    if features.churn_ratio > 0.5 and features.total_deletions > 20:
        score += 0.05
        factors.append(f"High code churn (ratio: {features.churn_ratio:.2f})")

    # Security issues
    if features.has_security_issue:
        score += 0.2
        factors.append("Security-sensitive patterns detected")

    # Bug risk density
    if features.files_changed > 0:
        density = features.bug_risk_count / features.files_changed
        if density > 3:
            score += 0.1
            factors.append(f"High bug-risk density ({density:.1f} per file)")

    # Warnings contribute mildly
    if features.warning_findings > 5:
        score += 0.05
        factors.append(f"{features.warning_findings} warnings")

    # Clamp to [0, 1]
    score = min(1.0, max(0.0, score))

    # Determine level
    if score >= 0.6:
        level = "high"
    elif score >= 0.3:
        level = "medium"
    else:
        level = "low"

    if not factors:
        factors.append("No significant risk factors identified")

    return RiskScore(
        level=level,
        score=round(score, 3),
        confidence=0.7,  # Heuristic confidence is moderate
        contributing_factors=factors,
        features=asdict(features),
        model_type="heuristic",
    )


class TrainedRiskModel:
    """Wrapper for a trained scikit-learn model."""

    def __init__(self):
        self.model = None
        self.scaler = None
        self.is_trained = False

    def train(self, feature_vectors: list[list[float]], labels: list[str]):
        """Train the model on historical data."""
        if not SKLEARN_AVAILABLE:
            raise RuntimeError("scikit-learn not installed")

        X = np.array(feature_vectors)
        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X)

        label_map = {"low": 0, "medium": 1, "high": 2}
        y = np.array([label_map.get(label, 0) for label in labels])

        self.model = GradientBoostingClassifier(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            random_state=42,
        )
        self.model.fit(X_scaled, y)
        self.is_trained = True

    def predict(self, features: RiskFeatures) -> RiskScore:
        """Predict risk using the trained model."""
        if not self.is_trained or self.model is None:
            raise RuntimeError("Model not trained")

        X = np.array([features.to_vector()])
        X_scaled = self.scaler.transform(X)

        pred = self.model.predict(X_scaled)[0]
        proba = self.model.predict_proba(X_scaled)[0]

        level_map = {0: "low", 1: "medium", 2: "high"}
        level = level_map[pred]
        confidence = float(max(proba))

        # Feature importance for contributing factors
        importances = self.model.feature_importances_
        top_indices = np.argsort(importances)[-3:][::-1]
        factors = []
        vec = features.to_vector()
        for idx in top_indices:
            if importances[idx] > 0.05:
                factors.append(
                    f"{FEATURE_NAMES[idx]}={vec[idx]:.1f} (importance: {importances[idx]:.2f})"
                )

        if not factors:
            factors.append("No dominant risk factors")

        return RiskScore(
            level=level,
            score=round(float(proba[pred]), 3),
            confidence=round(confidence, 3),
            contributing_factors=factors,
            features=asdict(features),
            model_type="trained_gradient_boosting",
        )

    def save(self, path: str):
        """Save the trained model to disk."""
        if not SKLEARN_AVAILABLE:
            raise RuntimeError("scikit-learn not installed")
        joblib.dump({"model": self.model, "scaler": self.scaler}, path)

    def load(self, path: str):
        """Load a trained model from disk."""
        if not SKLEARN_AVAILABLE:
            raise RuntimeError("scikit-learn not installed")
        data = joblib.load(path)
        self.model = data["model"]
        self.scaler = data["scaler"]
        self.is_trained = True


# Module-level trained model (loaded on demand)
_trained_model: TrainedRiskModel | None = None


def score_risk(analysis_result: dict, file_diffs: list | None = None) -> RiskScore:
    """Score the risk of a code change."""
    features = extract_features(analysis_result, file_diffs)

    if _trained_model is not None and _trained_model.is_trained:
        try:
            return _trained_model.predict(features)
        except Exception as e:
            logger.warning("Trained model prediction failed, falling back to heuristic: %s", e)

    return _heuristic_score(features)
