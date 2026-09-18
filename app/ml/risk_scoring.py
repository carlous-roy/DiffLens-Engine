"""Change-risk scoring.

Two sources of evidence are combined:

1. A gradient-boosting classifier (`HistGradientBoostingClassifier`) trained
   on the ApacheJIT dataset of defect-inducing commits predicts, from the
   change metrics in `app.ml.change_metrics`, the probability that a change
   of this shape introduces a defect. Its output is isotonic-calibrated.
   Training, evaluation and limitations are documented in docs/MODEL_CARD.md.
2. The static findings of this run, folded into a score with a noisy-OR
   over per-finding severity weights.

The final score is the noisy-OR of the two: the probability that at least
one of the two independent risk sources is real,

    score = 1 - (1 - p_model) * (1 - s_static)

and the level is low / medium / high at 0.3 and 0.6.

If the trained artefact is missing the module logs an error and falls back
to a hand-weighted heuristic; `model_type` says which path produced a score.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from app.ml.change_metrics import (
    DIFF_FEATURES,
    FULL_FEATURES,
    HISTORY_FEATURES,
    AuthorHistory,
    ChangeMetrics,
    compute_change_metrics,
)

logger = logging.getLogger(__name__)

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
ARTIFACT_PATH = ARTIFACT_DIR / "risk_model.joblib"
METADATA_PATH = ARTIFACT_DIR / "risk_model.json"
ARTIFACT_FORMAT_VERSION = 2

# Per-finding weights for the static score: each finding is treated as an
# independent indicator with this probability of being a real problem.
SEVERITY_WEIGHTS = {"critical": 0.30, "error": 0.12, "warning": 0.03, "info": 0.0}
LEVEL_THRESHOLDS = {"medium": 0.3, "high": 0.6}
TOP_ATTRIBUTIONS = 5

FEATURE_LABELS = {
    "la": "lines added",
    "ld": "lines deleted",
    "nf": "files changed",
    "nd": "directories changed",
    "ns": "subsystems changed",
    "ent": "change entropy",
    "age": "days since files last changed",
    "nuc": "prior changes per file",
    "aexp": "author's prior commits",
}


@dataclass
class StaticFeatures:
    """Counts extracted from this run's findings."""

    total_findings: int = 0
    critical_findings: int = 0
    error_findings: int = 0
    warning_findings: int = 0
    info_findings: int = 0
    max_complexity: int = 0
    avg_complexity: float = 0.0
    max_nesting_depth: int = 0
    naming_violations: int = 0
    bug_risk_count: int = 0
    has_security_issue: bool = False
    has_mutable_default: bool = False


def extract_static_features(analysis_result: dict) -> StaticFeatures:
    """Summarise the findings of an analysis run."""
    features = StaticFeatures()
    summary = analysis_result.get("summary", {})
    features.total_findings = summary.get("total_findings", 0)

    by_severity = summary.get("by_severity", {})
    features.critical_findings = by_severity.get("critical", 0)
    features.error_findings = by_severity.get("error", 0)
    features.warning_findings = by_severity.get("warning", 0)
    features.info_findings = by_severity.get("info", 0)

    by_analyzer = summary.get("by_analyzer", {})
    features.naming_violations = by_analyzer.get("naming", 0)
    features.bug_risk_count = by_analyzer.get("bug_risk", 0)

    complexities = []
    for cf in analysis_result.get("complexity_findings", []):
        features.max_nesting_depth = max(features.max_nesting_depth, cf.get("nesting_depth", 0))
        if cf.get("metric", "cyclomatic_complexity") != "cyclomatic_complexity":
            continue
        c = cf.get("complexity", 0)
        if c:
            complexities.append(c)
    if complexities:
        features.max_complexity = max(complexities)
        features.avg_complexity = round(sum(complexities) / len(complexities), 3)

    for bf in analysis_result.get("bug_risk_findings", []):
        rule_id = bf.get("rule_id", "")
        if rule_id in ("PY008", "JV001"):
            features.has_security_issue = True
        if rule_id == "PY003":
            features.has_mutable_default = True

    return features


def static_findings_score(static: StaticFeatures) -> float:
    """Noisy-OR of the severity weights of every finding: approaches 1 but
    each extra finding adds less than the one before."""
    survival = 1.0
    for severity, weight in SEVERITY_WEIGHTS.items():
        count = getattr(static, f"{severity}_findings", 0)
        survival *= (1.0 - weight) ** count
    return round(1.0 - survival, 4)


def combine_scores(model_probability: float, static_score: float) -> float:
    """Noisy-OR of the model probability and the static score."""
    p = min(1.0, max(0.0, model_probability))
    s = min(1.0, max(0.0, static_score))
    return round(1.0 - (1.0 - p) * (1.0 - s), 4)


def level_for(score: float) -> str:
    if score >= LEVEL_THRESHOLDS["high"]:
        return "high"
    if score >= LEVEL_THRESHOLDS["medium"]:
        return "medium"
    return "low"


@dataclass
class RiskScore:
    """Risk assessment result for a code change."""

    level: str  # low, medium, high
    score: float  # 0.0 to 1.0
    model_type: str  # "gradient_boosting" or "heuristic"
    model_probability: float | None
    static_score: float
    contributing_factors: list[str]
    attributions: list[dict]
    features: dict
    combination: dict = field(default_factory=dict)
    model_version: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class _Variant:
    """One fitted classifier with its calibrator and feature baselines."""

    def __init__(self, name: str, payload: dict):
        self.name = name
        self.model = payload["model"]
        self.calibrator = payload.get("calibrator")
        self.feature_names: list[str] = list(payload["feature_names"])
        self.baseline: dict[str, float] = dict(payload["baseline"])
        self.metrics: dict = dict(payload.get("metrics", {}))
        self._lock = threading.Lock()

    def probabilities(self, matrix: np.ndarray) -> np.ndarray:
        """Calibrated defect probabilities for a (n, features) matrix."""
        with self._lock:
            raw = self.model.predict_proba(matrix)[:, 1]
        if self.calibrator is not None:
            return np.clip(self.calibrator.predict(raw), 0.0, 1.0)
        return raw


class RiskModel:
    """The trained artefact: a `full` variant for changes with measured
    repository history and a `diff_only` variant for everything else."""

    EXPECTED_FEATURES = {"full": FULL_FEATURES, "diff_only": DIFF_FEATURES}

    def __init__(self, payload: dict, digest: str):
        self.digest = digest
        self.version = payload.get("version", "unknown")
        self.variants: dict[str, _Variant] = {}
        for name, expected in self.EXPECTED_FEATURES.items():
            if name not in payload.get("models", {}):
                raise ValueError(f"Artefact has no '{name}' model.")
            variant = _Variant(name, payload["models"][name])
            if variant.feature_names != expected:
                raise ValueError(
                    f"Artefact '{name}' feature order {variant.feature_names} does not "
                    f"match the runtime feature order {expected}."
                )
            self.variants[name] = variant

    @classmethod
    def load(cls, path: Path = ARTIFACT_PATH) -> RiskModel:
        import joblib  # pickle-based: only ever loaded from this package's own directory

        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        payload = joblib.load(path)
        if payload.get("format_version") != ARTIFACT_FORMAT_VERSION:
            raise ValueError(f"Unsupported artefact format: {payload.get('format_version')!r}")
        model = cls(payload, digest)
        try:
            import sklearn

            trained_with = payload.get("sklearn_version")
            if trained_with and trained_with != sklearn.__version__:
                logger.warning(
                    "Risk model was trained with scikit-learn %s but %s is installed.",
                    trained_with,
                    sklearn.__version__,
                )
        except ImportError:  # pragma: no cover
            pass
        return model

    def variant_for(self, metrics: ChangeMetrics) -> _Variant:
        return self.variants["full" if metrics.history_measured else "diff_only"]

    def predict(self, metrics: ChangeMetrics) -> tuple[float, list[dict], str]:
        """Return (calibrated probability, attributions, variant name).

        The contribution of a feature is the change in calibrated probability
        when that feature alone is reset to its training-set median. It is a
        single-feature ablation: exact for this model, cheap, and free of
        extra dependencies, but not a Shapley decomposition.
        """
        variant = self.variant_for(metrics)
        vector = np.array(metrics.vector(variant.feature_names), dtype=float)
        rows = [vector]
        for i, name in enumerate(variant.feature_names):
            ablated = vector.copy()
            ablated[i] = variant.baseline[name]
            rows.append(ablated)
        probs = variant.probabilities(np.vstack(rows))
        p_actual = float(probs[0])

        attributions = []
        for i, name in enumerate(variant.feature_names):
            attributions.append(
                {
                    "feature": name,
                    "label": FEATURE_LABELS.get(name, name),
                    "value": float(vector[i]),
                    "baseline": variant.baseline[name],
                    "contribution": round(p_actual - float(probs[i + 1]), 4),
                }
            )
        attributions.sort(key=lambda a: -abs(a["contribution"]))
        return round(p_actual, 4), attributions, variant.name

    def status(self) -> dict:
        return {
            name: {"features": v.feature_names, "metrics": v.metrics}
            for name, v in self.variants.items()
        }


_MODEL: RiskModel | None = None
_MODEL_LOAD_ATTEMPTED = False
_MODEL_LOCK = threading.Lock()


def load_risk_model(path: Path = ARTIFACT_PATH, force: bool = False) -> RiskModel | None:
    """Load the artefact once. Missing or broken artefacts log an error and
    leave the heuristic fallback in place."""
    global _MODEL, _MODEL_LOAD_ATTEMPTED
    with _MODEL_LOCK:
        if _MODEL_LOAD_ATTEMPTED and not force:
            return _MODEL
        _MODEL_LOAD_ATTEMPTED = True
        _MODEL = None
        if not path.exists():
            logger.error(
                "Risk model artefact %s is missing: risk scores will come from the "
                "heuristic fallback (model_type=heuristic). Run "
                "scripts/train_risk_model.py to build it.",
                path,
            )
            return None
        try:
            _MODEL = RiskModel.load(path)
        except Exception:
            logger.exception(
                "Risk model artefact %s could not be loaded: using the heuristic fallback.",
                path,
            )
            return None
        logger.info(
            "Loaded risk model %s (sha256 %s, variants: %s).",
            _MODEL.version,
            _MODEL.digest[:12],
            ", ".join(_MODEL.variants),
        )
        return _MODEL


def get_risk_model() -> RiskModel | None:
    return load_risk_model()


def reset_risk_model_cache() -> None:
    """Forget the loaded artefact (tests use this to exercise the fallback)."""
    global _MODEL, _MODEL_LOAD_ATTEMPTED
    with _MODEL_LOCK:
        _MODEL = None
        _MODEL_LOAD_ATTEMPTED = False


def risk_model_status() -> dict:
    model = get_risk_model()
    if model is None:
        return {"model_type": "heuristic", "loaded": False, "artefact": str(ARTIFACT_PATH)}
    return {
        "model_type": "gradient_boosting",
        "loaded": True,
        "version": model.version,
        "sha256": model.digest,
        "variants": model.status(),
    }


def score_risk(
    analysis_result: dict,
    file_diffs: list | None = None,
    history: AuthorHistory | None = None,
    metrics: ChangeMetrics | None = None,
) -> RiskScore:
    """Score the risk of a code change.

    `metrics` can be supplied by a caller that already computed them;
    otherwise they are derived from `file_diffs` (and `history`).
    """
    static = extract_static_features(analysis_result)
    if metrics is None:
        metrics = compute_change_metrics(file_diffs or [], history)
    s_static = static_findings_score(static)
    features = {**metrics.to_dict(), **asdict(static)}

    model = get_risk_model()
    if model is None:
        return _heuristic_score(metrics, static, s_static, features)

    p_model, attributions, variant = model.predict(metrics)
    score = combine_scores(p_model, s_static)
    factors = _model_factors(p_model, attributions, static, s_static, metrics)

    return RiskScore(
        level=level_for(score),
        score=score,
        model_type="gradient_boosting",
        model_probability=p_model,
        static_score=s_static,
        contributing_factors=factors,
        attributions=attributions[:TOP_ATTRIBUTIONS],
        features=features,
        combination={
            "method": "noisy_or",
            "formula": "score = 1 - (1 - model_probability) * (1 - static_score)",
            "severity_weights": SEVERITY_WEIGHTS,
            "thresholds": LEVEL_THRESHOLDS,
            "attribution_method": "baseline_ablation",
        },
        model_version=f"{model.version}/{variant}",
        warnings=_history_warnings(metrics),
    )


def _history_warnings(metrics: ChangeMetrics) -> list[str]:
    if metrics.history_measured:
        return []
    return [
        "Repository history was not measured "
        f"({', '.join(HISTORY_FEATURES)} unknown); the diff-only model variant was used."
    ]


def _model_factors(
    p_model: float,
    attributions: list[dict],
    static: StaticFeatures,
    s_static: float,
    metrics: ChangeMetrics,
) -> list[str]:
    factors = [f"Model probability of a defect-inducing change: {p_model:.0%}"]
    for attr in attributions[:3]:
        if abs(attr["contribution"]) < 0.01:
            continue
        sign = "+" if attr["contribution"] > 0 else "-"
        factors.append(
            f"{attr['label']} = {_fmt(attr['value'])} "
            f"({sign}{abs(attr['contribution']):.0%} vs. typical {_fmt(attr['baseline'])})"
        )
    factors.extend(_static_factors(static, s_static))
    if metrics.complexity_delta > 0:
        factors.append(f"Cyclomatic complexity added: +{metrics.complexity_delta}")
    if metrics.touches_tests:
        factors.append("Change includes test files")
    return factors


def _static_factors(static: StaticFeatures, s_static: float) -> list[str]:
    factors = []
    if static.critical_findings:
        factors.append(f"{static.critical_findings} critical finding(s) (e.g. eval() usage)")
    if static.error_findings:
        factors.append(f"{static.error_findings} error-level finding(s)")
    if static.max_complexity > 10:
        factors.append(f"High cyclomatic complexity ({static.max_complexity})")
    if static.max_nesting_depth >= 4:
        factors.append(f"Deep nesting ({static.max_nesting_depth} levels)")
    if s_static > 0:
        factors.append(f"Static findings score: {s_static:.0%}")
    return factors


def _fmt(value) -> str:
    if value is None:
        return "n/a"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}"


def _heuristic_score(
    metrics: ChangeMetrics,
    static: StaticFeatures,
    s_static: float,
    features: dict,
) -> RiskScore:
    """Hand-weighted fallback used only when the trained artefact is absent.

    It approximates the model's role with size-based rules and then applies
    the same noisy-OR combination with the static score.
    """
    p = 0.0
    factors = []
    if metrics.la > 200:
        p += 0.25
        factors.append(f"Large change ({metrics.la} lines added)")
    elif metrics.la > 100:
        p += 0.12
        factors.append(f"Moderate change size ({metrics.la} lines added)")
    if metrics.nf > 5:
        p += 0.10
        factors.append(f"Many files changed ({metrics.nf})")
    if metrics.ld > 20 and metrics.ld / (metrics.la + 1) > 0.5:
        p += 0.05
        factors.append("High code churn")
    if metrics.complexity_delta > 10:
        p += 0.10
        factors.append(f"Cyclomatic complexity added: +{metrics.complexity_delta}")
    p = min(1.0, p)
    factors.extend(_static_factors(static, s_static))
    score = combine_scores(p, s_static)
    if not factors:
        factors.append("No significant risk factors identified")

    return RiskScore(
        level=level_for(score),
        score=score,
        model_type="heuristic",
        model_probability=None,
        static_score=s_static,
        contributing_factors=factors,
        attributions=[],
        features=features,
        combination={
            "method": "noisy_or",
            "formula": "score = 1 - (1 - heuristic_size_score) * (1 - static_score)",
            "severity_weights": SEVERITY_WEIGHTS,
            "thresholds": LEVEL_THRESHOLDS,
        },
        warnings=["Risk model artefact not found; scores come from the heuristic fallback."],
    )


def read_model_metadata(path: Path = METADATA_PATH) -> dict | None:
    """The JSON sidecar written by the training script (metrics, dataset)."""
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
