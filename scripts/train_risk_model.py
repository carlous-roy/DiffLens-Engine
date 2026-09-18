#!/usr/bin/env python
"""Train the change-risk models on the ApacheJIT dataset.

Usage:
    python scripts/train_risk_model.py [--data-dir DIR] [--output-dir DIR]
                                       [--model-card PATH] [--seed N] [--csv FILE]

The script downloads the ApacheJIT archive from Zenodo (CC BY 4.0), keeps
`apachejit_total.csv`, splits every project in time (oldest commits for
fitting, then a calibration slice, newest 20% held out for testing), trains
two HistGradientBoostingClassifiers on Kamei-style change metrics, one for
when repository history is available and one over diff-only features, fits
an isotonic calibrator for each on the calibration slice, evaluates both on
the held-out period, computes attributions, and writes:

    <output-dir>/risk_model.joblib   the artefact loaded by app.ml.risk_scoring
    <output-dir>/risk_model.json     metadata and metrics (JSON)
    <model-card>                     docs/MODEL_CARD.md, generated from the same numbers

Every number in the model card comes from this run, so the card cannot
drift from the artefact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.ml.change_metrics import DIFF_FEATURES, FULL_FEATURES, HISTORY_FEATURES  # noqa: E402

logger = logging.getLogger("train_risk_model")

DATASET = {
    "name": "ApacheJIT",
    "citation": (
        "Hossein Keshavarz and Meiyappan Nagappan. ApacheJIT: A Large Dataset for "
        "Just-In-Time Defect Prediction. MSR 2022 (Data Showcase)."
    ),
    "url": "https://doi.org/10.5281/zenodo.5907847",
    "download_url": (
        "https://zenodo.org/api/records/5907847/files/apachejit_dataset_replication.zip/content"
    ),
    "archive_md5": "528bf0ee04b15976be6bf15f8efddc65",
    "member": "apachejit/dataset/apachejit_total.csv",
    "license": "CC BY 4.0",
}

# Every feature the dataset offers that can be measured at PR time. The
# feature-selection step below reports each subset; the shipped models use
# DIFF_FEATURES and FULL_FEATURES from app.ml.change_metrics.
DATASET_HISTORY_FEATURES = ["ndev", "age", "nuc", "aexp"]

TEST_FRACTION = 0.20  # newest share of each project held out
CALIBRATION_FRACTION = 0.15  # newest share of the training period used for calibration
SHAP_SAMPLE = 5000
PERMUTATION_REPEATS = 5

# Candidate configurations; per model, the one with the best ROC-AUC on the
# calibration slice (which precedes the test period) is kept.
CANDIDATES = [
    {"learning_rate": 0.05, "max_iter": 300, "max_leaf_nodes": 31, "min_samples_leaf": 50},
    {"learning_rate": 0.05, "max_iter": 500, "max_leaf_nodes": 31, "min_samples_leaf": 100},
    {"learning_rate": 0.1, "max_iter": 200, "max_leaf_nodes": 31, "min_samples_leaf": 50},
    {"learning_rate": 0.1, "max_iter": 300, "max_leaf_nodes": 63, "min_samples_leaf": 100},
    {"learning_rate": 0.03, "max_iter": 600, "max_leaf_nodes": 15, "min_samples_leaf": 50},
]

MODELS = {
    "full": FULL_FEATURES,  # used when repository history was measured
    "diff_only": DIFF_FEATURES,  # used otherwise
}


@dataclass
class Split:
    fit: pd.DataFrame
    calibration: pd.DataFrame
    test: pd.DataFrame


@dataclass
class TrainedModel:
    name: str
    feature_names: list[str]
    clf: HistGradientBoostingClassifier
    calibrator: IsotonicRegression
    params: dict
    trials: list[dict]
    baseline: dict[str, float]


# ---------------------------------------------------------------- data ----


def download_dataset(data_dir: Path) -> Path:
    """Fetch apachejit_total.csv into `data_dir`, verifying the archive checksum."""
    csv_path = data_dir / "apachejit_total.csv"
    if csv_path.exists():
        return csv_path
    data_dir.mkdir(parents=True, exist_ok=True)
    archive = data_dir / "apachejit_dataset_replication.zip"
    if not archive.exists():
        import urllib.request

        logger.info("Downloading %s", DATASET["download_url"])
        with urllib.request.urlopen(DATASET["download_url"]) as resp:
            archive.write_bytes(resp.read())
    digest = hashlib.md5(archive.read_bytes()).hexdigest()  # integrity check only
    if digest != DATASET["archive_md5"]:
        raise SystemExit(f"Checksum mismatch for {archive}: {digest}")
    with zipfile.ZipFile(archive) as zf:
        csv_path.write_bytes(zf.read(DATASET["member"]))
    return csv_path


def load_dataset(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    required = {"commit_id", "project", "buggy", "author_date", *DIFF_FEATURES}
    required |= set(DATASET_HISTORY_FEATURES)
    missing = required - set(df.columns)
    if missing:
        raise SystemExit(f"Dataset is missing columns: {sorted(missing)}")
    df["buggy"] = df["buggy"].astype(str).str.lower().eq("true").astype(int)
    df["author_date"] = pd.to_numeric(df["author_date"])
    return df


def temporal_split(
    df: pd.DataFrame,
    test_fraction: float = TEST_FRACTION,
    calibration_fraction: float = CALIBRATION_FRACTION,
) -> Split:
    """Per-project split by author date: oldest for fitting, then calibration, newest for test.

    Every project contributes its own newest `test_fraction` of commits, so
    the test period is strictly later than the training period within each
    project, and the calibration slice is the newest part of what remains.
    """
    fit_parts, cal_parts, test_parts = [], [], []
    for _, group in df.groupby("project", sort=True):
        ordered = group.sort_values(["author_date", "commit_id"], kind="mergesort")
        n = len(ordered)
        n_test = int(round(n * test_fraction))
        train = ordered.iloc[: n - n_test]
        n_cal = int(round(len(train) * calibration_fraction))
        fit_parts.append(train.iloc[: len(train) - n_cal])
        cal_parts.append(train.iloc[len(train) - n_cal :])
        test_parts.append(ordered.iloc[n - n_test :])
    return Split(
        fit=pd.concat(fit_parts, ignore_index=True),
        calibration=pd.concat(cal_parts, ignore_index=True),
        test=pd.concat(test_parts, ignore_index=True),
    )


def matrix(df: pd.DataFrame, feature_names: list[str]) -> np.ndarray:
    return df[feature_names].to_numpy(dtype=float)


# ------------------------------------------------------------- training ----


def fit_classifier(params: dict, X: np.ndarray, y: np.ndarray, seed: int):
    clf = HistGradientBoostingClassifier(random_state=seed, early_stopping=False, **params)
    clf.fit(X, y)
    return clf


def train_model(name: str, feature_names: list[str], split: Split, seed: int) -> TrainedModel:
    X_fit, y_fit = matrix(split.fit, feature_names), split.fit["buggy"].to_numpy()
    X_cal = matrix(split.calibration, feature_names)
    y_cal = split.calibration["buggy"].to_numpy()

    trials, best = [], None
    for params in CANDIDATES:
        start = time.time()
        clf = fit_classifier(params, X_fit, y_fit, seed)
        auc = roc_auc_score(y_cal, clf.predict_proba(X_cal)[:, 1])
        trials.append({**params, "calibration_roc_auc": round(float(auc), 4)})
        logger.info(
            "[%s] %s -> calibration ROC-AUC %.4f (%.0fs)", name, params, auc, time.time() - start
        )
        if best is None or auc > best[0]:
            best = (auc, clf, params)

    _, clf, params = best
    calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    calibrator.fit(clf.predict_proba(X_cal)[:, 1], y_cal)
    baseline = {f: float(split.fit[f].median()) for f in feature_names}
    return TrainedModel(name, list(feature_names), clf, calibrator, params, trials, baseline)


# ----------------------------------------------------------- evaluation ----


def metrics_for(y: np.ndarray, p: np.ndarray) -> dict:
    return {
        "roc_auc": round(float(roc_auc_score(y, p)), 4),
        "pr_auc": round(float(average_precision_score(y, p)), 4),
        "brier": round(float(brier_score_loss(y, p)), 4),
    }


def evaluate(model: TrainedModel, split: Split) -> dict:
    test = split.test
    y = test["buggy"].to_numpy()
    raw = model.clf.predict_proba(matrix(test, model.feature_names))[:, 1]
    cal = np.clip(model.calibrator.predict(raw), 0, 1)
    result = {"raw": metrics_for(y, raw), "calibrated": metrics_for(y, cal), "per_project": []}
    for project, idx in test.groupby("project").indices.items():
        y_p = y[idx]
        if len(np.unique(y_p)) < 2:
            continue
        result["per_project"].append(
            {
                "project": project,
                "n": int(len(idx)),
                "prevalence": round(float(y_p.mean()), 3),
                "roc_auc": round(float(roc_auc_score(y_p, cal[idx])), 4),
                "pr_auc": round(float(average_precision_score(y_p, cal[idx])), 4),
            }
        )
    return result


def feature_selection(split: Split, params: dict, seed: int) -> list[dict]:
    """Held-out ROC-AUC for the candidate feature subsets, with one fixed configuration.

    This is what decided the shipped feature lists: it is recorded so the
    choice can be checked and revisited when the dataset or features change.
    """
    train = pd.concat([split.fit, split.calibration], ignore_index=True)
    y_train, y_test = train["buggy"].to_numpy(), split.test["buggy"].to_numpy()
    subsets = [("diff only", DIFF_FEATURES)]
    subsets += [(f"diff + {h}", DIFF_FEATURES + [h]) for h in DATASET_HISTORY_FEATURES]
    subsets += [
        ("diff + age + nuc + aexp (shipped full model)", FULL_FEATURES),
        ("diff + all four history features", DIFF_FEATURES + DATASET_HISTORY_FEATURES),
    ]
    rows = []
    for label, cols in subsets:
        clf = fit_classifier(params, matrix(train, cols), y_train, seed)
        p = clf.predict_proba(matrix(split.test, cols))[:, 1]
        rows.append(
            {
                "features": label,
                "roc_auc": round(float(roc_auc_score(y_test, p)), 4),
                "pr_auc": round(float(average_precision_score(y_test, p)), 4),
            }
        )
        logger.info("feature subset %-48s ROC-AUC %.4f", label, rows[-1]["roc_auc"])
    return rows


def attributions(model: TrainedModel, split: Split, seed: int) -> dict:
    """Global attributions: permutation importance and, when available, mean |SHAP|."""
    test = split.test
    X, y = matrix(test, model.feature_names), test["buggy"].to_numpy()
    perm = permutation_importance(
        model.clf,
        X,
        y,
        scoring="roc_auc",
        n_repeats=PERMUTATION_REPEATS,
        random_state=seed,
        n_jobs=1,
    )
    result = {
        "permutation_importance_roc_auc": {
            name: {"mean": round(float(m), 4), "std": round(float(s), 4)}
            for name, m, s in zip(
                model.feature_names, perm.importances_mean, perm.importances_std, strict=True
            )
        },
        "mean_abs_shap_log_odds": None,
    }
    try:
        import shap
    except ImportError:
        logger.warning("shap is not installed; only permutation importance was computed.")
        return result

    sample = test.sample(n=min(SHAP_SAMPLE, len(test)), random_state=seed)
    explainer = shap.TreeExplainer(model.clf)
    values = np.asarray(explainer.shap_values(matrix(sample, model.feature_names)))
    if values.ndim == 3:  # (n, features, classes) in some shap versions
        values = values[:, :, -1]
    mean_abs = np.abs(values).mean(axis=0)
    result["mean_abs_shap_log_odds"] = {
        name: round(float(v), 4) for name, v in zip(model.feature_names, mean_abs, strict=True)
    }
    result["shap_version"] = shap.__version__
    result["shap_sample_size"] = int(len(sample))
    return result


# ------------------------------------------------------------- outputs ----


def dataset_summary(df: pd.DataFrame, split: Split) -> dict:
    years = pd.to_datetime(df["author_date"], unit="s", utc=True).dt.year
    y_test = split.test["buggy"].to_numpy()
    return {
        **DATASET,
        "n_commits": int(len(df)),
        "n_projects": int(df["project"].nunique()),
        "projects": sorted(df["project"].unique().tolist()),
        "years": [int(years.min()), int(years.max())],
        "prevalence": round(float(df["buggy"].mean()), 4),
        "n_fit": int(len(split.fit)),
        "n_calibration": int(len(split.calibration)),
        "n_test": int(len(split.test)),
        "test_prevalence": round(float(y_test.mean()), 4),
        "baseline_brier_prevalence": round(
            float(brier_score_loss(y_test, np.full(len(y_test), y_test.mean()))), 4
        ),
    }


def write_artifact(
    output_dir: Path, models: dict[str, TrainedModel], meta: dict
) -> tuple[Path, str]:
    import joblib
    import sklearn

    output_dir.mkdir(parents=True, exist_ok=True)
    artifact = output_dir / "risk_model.joblib"
    payload = {
        "format_version": 2,
        "version": meta["version"],
        "sklearn_version": sklearn.__version__,
        "history_features": HISTORY_FEATURES,
        "models": {
            name: {
                "feature_names": m.feature_names,
                "model": m.clf,
                "calibrator": m.calibrator,
                "baseline": m.baseline,
                "params": m.params,
                "metrics": meta["models"][name]["evaluation"]["calibrated"],
            }
            for name, m in models.items()
        },
    }
    joblib.dump(payload, artifact, compress=("zlib", 6))
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    return artifact, digest


def render_model_card(meta: dict) -> str:
    ds = meta["dataset"]
    full = meta["models"]["full"]
    diff_only = meta["models"]["diff_only"]

    def cond_row(label, m):
        return f"| {label} | {m['roc_auc']:.3f} | {m['pr_auc']:.3f} | {m['brier']:.4f} |"

    lines = [
        "# Model card: change-risk models",
        "",
        f"Generated by `scripts/train_risk_model.py` on {meta['trained_at']}. "
        "Do not edit by hand; re-run the script.",
        "",
        "## Models",
        "",
        "Two `sklearn.ensemble.HistGradientBoostingClassifier` models, each with an",
        "isotonic calibrator (`sklearn.isotonic.IsotonicRegression`) on its output:",
        "",
        f"- `full`, features `{'`, `'.join(full['feature_names'])}`, used when the",
        "  service could measure repository history for the change (a GitHub token",
        "  is configured and the pull request flow fetched commit history).",
        f"- `diff_only`, features `{'`, `'.join(diff_only['feature_names'])}`, used for",
        "  diffs submitted through the API and whenever history is unavailable.",
        "",
        f"Parameters: full `{json.dumps(full['params'])}`; "
        f"diff_only `{json.dumps(diff_only['params'])}`. Each was chosen from "
        f"{len(CANDIDATES)} candidates by ROC-AUC on the calibration slice.",
        "",
        f"Artefact: `app/ml/artifacts/risk_model.joblib`, "
        f"{meta['artifact_size_bytes'] / 1e6:.2f} MB, sha256 `{meta['artifact_sha256']}`. "
        f"scikit-learn {meta['versions']['sklearn']}, numpy {meta['versions']['numpy']}.",
        "",
        "## Task",
        "",
        "Just-in-time defect prediction: given the metrics of a code change, estimate the",
        "probability that the change introduces a defect that is later fixed. DiffLens",
        "uses the calibrated probability as the change-metrics half of its risk score;",
        "the other half is the static findings (see `app/ml/risk_scoring.py`).",
        "",
        "## Data",
        "",
        f"- Dataset: {ds['name']} ({ds['citation']}).",
        f"- Source: {ds['url']}, archive `apachejit_dataset_replication.zip`, "
        f"MD5 `{ds['archive_md5']}`, file `{ds['member']}`.",
        f"- Licence: {ds['license']} (Zenodo record). The dataset is not redistributed in this",
        "  repository; the training script downloads it.",
        f"- {ds['n_commits']:,} commits from {ds['n_projects']} Apache projects, "
        f"{ds['years'][0]}–{ds['years'][1]}, {ds['prevalence']:.1%} labelled "
        "defect-inducing (`buggy`).",
        "- Projects: " + ", ".join(p.split("/", 1)[-1] for p in ds["projects"]) + ".",
        "",
        "### Feature definitions",
        "",
        "| Feature | Meaning | Measured at PR time from |",
        "|---|---|---|",
        "| `la`, `ld` | lines added / deleted | the diff |",
        "| `nf`, `nd`, `ns` | files, directories, top-level subsystems changed | the diff |",
        "| `ent` | Shannon entropy (base 2) of changed lines across files, unnormalised "
        "| the diff |",
        "| `age` | mean over changed files of days since the file was last changed "
        "| GitHub commit history |",
        "| `nuc` | mean over changed files of the number of prior commits touching the file "
        "| GitHub commit history |",
        "| `aexp` | number of prior commits by the author in the repository "
        "| GitHub commit history |",
        "| `ndev` | mean over changed files of the number of distinct prior authors "
        "| measured and reported, not a model input (see below) |",
        "",
        "The per-file averaging for `ndev`, `nuc` and `age` matches the fractional values",
        "in the dataset (for example `ndev = 0.25` on a four-file commit). The archive",
        "ships the metrics precomputed (`apache_metrics_kamei.csv`) without the script that",
        "produced them, so the PR-time implementation in `app/github/history.py` follows",
        "the definitions above and may differ in detail from the original extraction.",
        "",
        "## Split",
        "",
        f"Per project, commits are ordered by author date. The newest {TEST_FRACTION:.0%} form the",
        f"test set, the newest {CALIBRATION_FRACTION:.0%} of the remainder the calibration "
        "slice, and",
        "the rest the fit set. No commit from the test period is used for fitting, model",
        "selection, feature selection or calibration.",
        "",
        "| Fit | Calibration | Test |",
        "|---|---|---|",
        f"| {ds['n_fit']:,} | {ds['n_calibration']:,} | {ds['n_test']:,} |",
        "",
        "## Feature selection",
        "",
        "Held-out ROC-AUC of one fixed configuration trained on fit + calibration commits",
        "for each candidate subset of the dataset's PR-time features:",
        "",
        "| Features | ROC-AUC | PR-AUC |",
        "|---|---|---|",
    ]
    for row in meta["feature_selection"]:
        lines.append(f"| {row['features']} | {row['roc_auc']:.3f} | {row['pr_auc']:.3f} |")
    lines += [
        "",
        "`ndev` lowers held-out performance: the number of prior authors per file grows",
        "as a project ages, so the association learned on the training period does not",
        "carry over to the test period. It is therefore measured and reported but not",
        "fed to the models. `age`, `nuc` and `aexp` each improve on the diff-only set.",
        "",
        "## Results on the held-out period",
        "",
        f"Test prevalence {ds['test_prevalence']:.1%}; a constant prediction of the prevalence",
        f"would score Brier {ds['baseline_brier_prevalence']:.4f}.",
        "",
        "| Model | ROC-AUC | PR-AUC | Brier |",
        "|---|---|---|---|",
        cond_row("full, raw", full["evaluation"]["raw"]),
        cond_row("full, calibrated", full["evaluation"]["calibrated"]),
        cond_row("diff_only, raw", diff_only["evaluation"]["raw"]),
        cond_row("diff_only, calibrated", diff_only["evaluation"]["calibrated"]),
        "",
        "### Per project (calibrated, test period)",
        "",
        "| Project | n | Prevalence | full ROC-AUC | full PR-AUC "
        "| diff_only ROC-AUC | diff_only PR-AUC |",
        "|---|---|---|---|---|---|---|",
    ]
    diff_rows = {r["project"]: r for r in diff_only["evaluation"]["per_project"]}
    for row in full["evaluation"]["per_project"]:
        d = diff_rows.get(row["project"], {})
        lines.append(
            f"| {row['project'].split('/', 1)[-1]} | {row['n']:,} | {row['prevalence']:.1%} | "
            f"{row['roc_auc']:.3f} | {row['pr_auc']:.3f} | "
            f"{d.get('roc_auc', float('nan')):.3f} | {d.get('pr_auc', float('nan')):.3f} |"
        )
    lines += [
        "",
        "## Attributions",
        "",
        "Permutation importance is the mean drop in test ROC-AUC when one feature is",
        f"shuffled ({PERMUTATION_REPEATS} repeats).",
    ]
    for name in ("full", "diff_only"):
        attr = meta["models"][name]["attributions"]
        lines += ["", f"### `{name}` model", ""]
        if attr.get("mean_abs_shap_log_odds"):
            lines.append(
                f"Mean |SHAP| is over a random sample of {attr['shap_sample_size']:,} test "
                f"commits (TreeExplainer, shap {attr['shap_version']}, log-odds units)."
            )
            lines += ["", "| Feature | Permutation importance | Mean \\|SHAP\\| |", "|---|---|---|"]
            for f in meta["models"][name]["feature_names"]:
                pi = attr["permutation_importance_roc_auc"][f]
                lines.append(
                    f"| `{f}` | {pi['mean']:.4f} ± {pi['std']:.4f} | "
                    f"{attr['mean_abs_shap_log_odds'][f]:.3f} |"
                )
        else:
            lines += ["", "| Feature | Permutation importance |", "|---|---|"]
            for f in meta["models"][name]["feature_names"]:
                pi = attr["permutation_importance_roc_auc"][f]
                lines.append(f"| `{f}` | {pi['mean']:.4f} ± {pi['std']:.4f} |")
    lines += [
        "",
        "At prediction time the service reports per-feature attributions by baseline",
        "ablation: the change in calibrated probability when one feature is reset to its",
        "training-set median. It is exact for the model but is a single-feature",
        "ablation, not a Shapley decomposition.",
        "",
        "## Limitations",
        "",
        "- The labels come from the SZZ-style linking of fixes to inducing commits used",
        '  by ApacheJIT; they are noisy, and a "defect" is whatever those projects',
        "  fixed and linked to an issue.",
        "- All training projects are Java-heavy Apache projects with mature review",
        "  processes. Probabilities on other ecosystems, languages, or small personal",
        "  repositories are not calibrated for them.",
        "- The models see commit-level metrics. A pull request is scored as one change,",
        "  which for multi-commit PRs is coarser than the training unit.",
        "- The static findings enter through a fixed noisy-OR combination, not through",
        "  the learned models, because the dataset has no static-analysis features.",
        "- ROC-AUC around 0.8 is typical for this task; the score ranks changes",
        "  usefully but is not a defect detector.",
        "",
        "## Reproduce",
        "",
        "```",
        "pip install -r requirements-dev.txt",
        "python scripts/train_risk_model.py --data-dir data/apachejit",
        "```",
        "",
        f"Seed {meta['seed']}. Model selection trials (calibration ROC-AUC):",
        "",
        "| learning_rate | max_iter | max_leaf_nodes | min_samples_leaf | full | diff_only |",
        "|---|---|---|---|---|---|",
    ]
    for t_full, t_diff in zip(full["trials"], diff_only["trials"], strict=True):
        lines.append(
            f"| {t_full['learning_rate']} | {t_full['max_iter']} | {t_full['max_leaf_nodes']} | "
            f"{t_full['min_samples_leaf']} | {t_full['calibration_roc_auc']:.4f} | "
            f"{t_diff['calibration_roc_auc']:.4f} |"
        )
    lines.append("")
    return "\n".join(lines)


# ----------------------------------------------------------------- main ----


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data-dir", type=Path, default=REPO_ROOT / "data" / "apachejit")
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "app" / "ml" / "artifacts")
    parser.add_argument("--model-card", type=Path, default=REPO_ROOT / "docs" / "MODEL_CARD.md")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--csv", type=Path, help="Use this apachejit_total.csv instead of downloading."
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    csv_path = args.csv or download_dataset(args.data_dir)
    df = load_dataset(csv_path)
    logger.info("Loaded %d commits from %d projects", len(df), df["project"].nunique())
    split = temporal_split(df)
    logger.info(
        "Split: fit=%d calibration=%d test=%d",
        len(split.fit),
        len(split.calibration),
        len(split.test),
    )

    models = {name: train_model(name, cols, split, args.seed) for name, cols in MODELS.items()}
    selection = feature_selection(split, models["full"].params, args.seed)

    import sklearn

    meta = {
        "version": f"apachejit-hgb-{datetime.now(UTC).strftime('%Y%m%d')}",
        "trained_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "seed": args.seed,
        "dataset": dataset_summary(df, split),
        "feature_selection": selection,
        "models": {
            name: {
                "feature_names": m.feature_names,
                "params": m.params,
                "trials": m.trials,
                "baseline": m.baseline,
                "evaluation": evaluate(m, split),
                "attributions": attributions(m, split, args.seed),
            }
            for name, m in models.items()
        },
        "versions": {
            "sklearn": sklearn.__version__,
            "numpy": np.__version__,
            "pandas": pd.__version__,
        },
    }
    artifact, digest = write_artifact(args.output_dir, models, meta)
    meta["artifact_sha256"] = digest
    meta["artifact_size_bytes"] = artifact.stat().st_size
    (args.output_dir / "risk_model.json").write_text(json.dumps(meta, indent=2) + "\n")

    args.model_card.parent.mkdir(parents=True, exist_ok=True)
    args.model_card.write_text(render_model_card(meta))

    for name in MODELS:
        m = meta["models"][name]["evaluation"]["calibrated"]
        logger.info(
            "[%s] test ROC-AUC %.3f, PR-AUC %.3f, Brier %.4f",
            name,
            m["roc_auc"],
            m["pr_auc"],
            m["brier"],
        )
    logger.info("Artefact %.2f MB at %s", meta["artifact_size_bytes"] / 1e6, artifact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
