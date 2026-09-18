"""Tests for the change metrics computed from a diff."""

import math

import pytest

from app.analysis.diff_parser import parse_diff
from app.ml.change_metrics import (
    DIFF_FEATURES,
    FULL_FEATURES,
    HISTORY_FEATURES,
    AuthorHistory,
    ChangeMetrics,
    change_entropy,
    compute_change_metrics,
    is_test_path,
)


def _diff(files: dict[str, tuple[int, int]]) -> str:
    """Build a diff with `added`/`removed` line counts per path."""
    parts = []
    for path, (added, removed) in files.items():
        parts.append(f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n")
        parts.append(f"@@ -1,{removed + 1} +1,{added + 1} @@\n context\n")
        parts.extend(f"-old{i}\n" for i in range(removed))
        parts.extend(f"+new{i}\n" for i in range(added))
    return "".join(parts)


class TestEntropy:
    def test_single_file_is_zero(self):
        assert change_entropy([40]) == 0.0

    def test_two_equal_files_is_one_bit(self):
        assert change_entropy([10, 10]) == pytest.approx(1.0)

    def test_maximum_is_log2_n(self):
        assert change_entropy([5, 5, 5, 5]) == pytest.approx(2.0)

    def test_skewed_split_is_below_maximum(self):
        assert 0 < change_entropy([90, 10]) < 1.0

    def test_empty_files_ignored(self):
        assert change_entropy([0, 0]) == 0.0
        assert change_entropy([7, 0]) == 0.0


class TestComputeChangeMetrics:
    def test_counts_and_structure(self):
        diff = _diff(
            {
                "src/main/java/App.java": (30, 10),
                "src/main/java/util/Helper.java": (10, 0),
                "docs/README.md": (5, 5),
            }
        )
        metrics = compute_change_metrics(parse_diff(diff))
        assert (metrics.la, metrics.ld, metrics.nf) == (45, 15, 3)
        assert metrics.nd == 3  # src/main/java, src/main/java/util, docs
        assert metrics.ns == 2  # src, docs
        assert metrics.ent == pytest.approx(change_entropy([40, 10, 10]))
        assert metrics.touches_tests is False
        assert metrics.history_measured is False
        assert metrics.history_source == "unavailable"

    def test_root_level_file_counts_as_its_own_subsystem(self):
        metrics = compute_change_metrics(parse_diff(_diff({"setup.py": (1, 0)})))
        assert metrics.nd == 1
        assert metrics.ns == 1

    def test_touches_tests(self):
        metrics = compute_change_metrics(
            parse_diff(_diff({"app/x.py": (1, 0), "tests/test_x.py": (1, 0)}))
        )
        assert metrics.touches_tests is True

    def test_complexity_delta_from_added_and_removed_functions(self):
        diff = (
            "diff --git a/m.py b/m.py\n--- a/m.py\n+++ b/m.py\n"
            "@@ -1,4 +1,6 @@\n"
            "-def old(x):\n"
            "-    if x:\n"
            "-        return 1\n"
            "+def new(x):\n"
            "+    if x and x > 1:\n"
            "+        return 1\n"
            "+    for i in x:\n"
            "+        pass\n"
            " y = 1\n"
        )
        metrics = compute_change_metrics(parse_diff(diff))
        assert metrics.complexity_removed == 2  # base + if
        assert metrics.complexity_added == 4  # base + if + and + for
        assert metrics.complexity_delta == 2

    def test_history_is_attached(self):
        history = AuthorHistory(ndev=1.5, age=12.0, nuc=4.0, aexp=100.0, files_measured=2)
        metrics = compute_change_metrics(parse_diff(_diff({"a.py": (1, 0)})), history)
        assert metrics.history_measured is True
        assert metrics.history_source == "github"
        assert metrics.ndev == 1.5
        assert metrics.vector(FULL_FEATURES)[-3:] == [12.0, 4.0, 100.0]

    def test_vector_uses_nan_for_unmeasured(self):
        metrics = ChangeMetrics(la=3, ld=1, nf=1, nd=1, ns=1, ent=0.0)
        vector = metrics.vector(FULL_FEATURES)
        assert vector[: len(DIFF_FEATURES)] == [3.0, 1.0, 1.0, 1.0, 1.0, 0.0]
        assert all(math.isnan(v) for v in vector[len(DIFF_FEATURES) :])

    def test_empty_diff(self):
        metrics = compute_change_metrics([])
        assert metrics.to_dict()["nf"] == 0
        assert metrics.ent == 0.0


class TestFeatureLists:
    def test_history_features_exclude_ndev(self):
        assert HISTORY_FEATURES == ["age", "nuc", "aexp"]
        assert FULL_FEATURES == DIFF_FEATURES + HISTORY_FEATURES


@pytest.mark.parametrize(
    "path,expected",
    [
        ("tests/test_x.py", True),
        ("app/tests/helpers.py", True),
        ("src/test/java/FooTest.java", True),
        ("src/main/java/FooTest.java", True),
        ("lib/foo_test.py", True),
        ("web/app.spec.ts", True),
        ("app/testing_utils.py", False),
        ("src/main/java/Foo.java", False),
        ("contest.py", False),
    ],
)
def test_is_test_path(path, expected):
    assert is_test_path(path) is expected
