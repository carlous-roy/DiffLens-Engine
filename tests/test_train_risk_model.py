"""Tests for the training script's data handling, on a small synthetic frame.

The real dataset is downloaded by the script; these tests only check the
parts that decide what the model sees and how the results are reported.
"""

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

pd = pytest.importorskip("pandas")

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "train_risk_model.py"


@pytest.fixture(scope="module")
def train():
    spec = importlib.util.spec_from_file_location("train_risk_model", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["train_risk_model"] = module
    spec.loader.exec_module(module)
    return module


def _frame(n_per_project=100, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for project in ("apache/a", "apache/b"):
        dates = np.sort(rng.integers(1_000_000, 2_000_000, size=n_per_project))
        for i, date in enumerate(dates):
            la = int(rng.integers(0, 500))
            rows.append(
                {
                    "commit_id": f"{project}-{i}",
                    "project": project,
                    "buggy": "True" if rng.random() < 0.2 + la / 2000 else "False",
                    "author_date": int(date),
                    "la": la,
                    "ld": int(rng.integers(0, 100)),
                    "nf": int(rng.integers(1, 10)),
                    "nd": int(rng.integers(1, 5)),
                    "ns": int(rng.integers(1, 3)),
                    "ent": float(rng.random() * 2),
                    "ndev": float(rng.random() * 5),
                    "age": float(rng.random() * 100),
                    "nuc": float(rng.random() * 30),
                    "aexp": float(rng.integers(0, 300)),
                }
            )
    return pd.DataFrame(rows)


class TestTemporalSplit:
    def test_split_is_per_project_and_ordered_in_time(self, train, tmp_path):
        csv = tmp_path / "apachejit_total.csv"
        _frame().to_csv(csv, index=False)
        df = train.load_dataset(csv)
        assert set(df["buggy"].unique()) <= {0, 1}

        split = train.temporal_split(df, test_fraction=0.2, calibration_fraction=0.25)
        assert len(split.test) == 40  # 20% of each of two projects
        assert len(split.calibration) == 40  # 25% of the remaining 80 per project
        assert len(split.fit) == 120
        for project in df["project"].unique():
            fit = split.fit[split.fit.project == project]["author_date"]
            cal = split.calibration[split.calibration.project == project]["author_date"]
            test = split.test[split.test.project == project]["author_date"]
            assert fit.max() <= cal.min()
            assert cal.max() <= test.min()

    def test_no_commit_appears_twice(self, train, tmp_path):
        csv = tmp_path / "apachejit_total.csv"
        _frame().to_csv(csv, index=False)
        split = train.temporal_split(train.load_dataset(csv))
        ids = pd.concat([split.fit, split.calibration, split.test])["commit_id"]
        assert ids.is_unique
        assert len(ids) == 200

    def test_missing_columns_rejected(self, train, tmp_path):
        csv = tmp_path / "bad.csv"
        pd.DataFrame({"commit_id": ["x"], "project": ["p"]}).to_csv(csv, index=False)
        with pytest.raises(SystemExit, match="missing columns"):
            train.load_dataset(csv)


class TestFeatureOrder:
    def test_models_use_the_runtime_feature_lists(self, train):
        from app.ml.change_metrics import DIFF_FEATURES, FULL_FEATURES

        assert train.MODELS == {"full": FULL_FEATURES, "diff_only": DIFF_FEATURES}
        assert "ndev" not in FULL_FEATURES


class TestEndToEndOnSyntheticData:
    def test_train_evaluate_and_render(self, train, tmp_path, monkeypatch):
        """Exercise training, evaluation, artefact writing and the card on a
        tiny frame, with a single small candidate to keep it fast."""
        monkeypatch.setattr(
            train,
            "CANDIDATES",
            [{"learning_rate": 0.1, "max_iter": 20, "max_leaf_nodes": 7, "min_samples_leaf": 5}],
        )
        monkeypatch.setattr(train, "SHAP_SAMPLE", 50)
        monkeypatch.setattr(train, "PERMUTATION_REPEATS", 1)
        csv = tmp_path / "apachejit_total.csv"
        _frame(n_per_project=300).to_csv(csv, index=False)
        out = tmp_path / "artifacts"
        card = tmp_path / "MODEL_CARD.md"

        assert (
            train.main(["--csv", str(csv), "--output-dir", str(out), "--model-card", str(card)])
            == 0
        )

        assert (out / "risk_model.joblib").exists()
        meta = pd.read_json(out / "risk_model.json", typ="series")
        assert set(meta["models"]) == {"full", "diff_only"}
        for name in ("full", "diff_only"):
            metrics = meta["models"][name]["evaluation"]["calibrated"]
            assert 0.0 <= metrics["roc_auc"] <= 1.0
            assert 0.0 <= metrics["brier"] <= 1.0
        text = card.read_text()
        assert "## Results on the held-out period" in text
        assert "## Feature selection" in text
        assert meta["artifact_sha256"] in text

        from app.ml.risk_scoring import RiskModel

        model = RiskModel.load(out / "risk_model.joblib")
        assert set(model.variants) == {"full", "diff_only"}
