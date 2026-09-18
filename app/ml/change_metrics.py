"""Change metrics computed from a diff at pull-request time.

These are the Kamei-style just-in-time defect prediction features the risk
model is trained on (see docs/MODEL_CARD.md), plus two metrics that come
from the Tree-sitter analyzers and are used by the risk combination rather
than the learned model: the complexity delta and whether tests are touched.
"""

from __future__ import annotations

import math
import posixpath
import re
from dataclasses import asdict, dataclass

from app.analysis.complexity import analyze_complexity
from app.analysis.diff_parser import FileDiff

# Features computed from the diff alone, in the order the models were trained with.
DIFF_FEATURES = ["la", "ld", "nf", "nd", "ns", "ent"]
# Features that need repository history. The artefact holds one model over
# DIFF_FEATURES + HISTORY_FEATURES for when these were measured and one over
# DIFF_FEATURES alone for when they were not. `ndev` is measured and reported
# but deliberately not a model input; docs/MODEL_CARD.md has the evidence.
HISTORY_FEATURES = ["age", "nuc", "aexp"]
FULL_FEATURES = DIFF_FEATURES + HISTORY_FEATURES

_TEST_PATH_RE = re.compile(
    r"(^|/)(tests?|testing|__tests__|spec|specs)(/|$)"
    r"|(^|/)test_[^/]*\.py$"
    r"|_test\.py$"
    r"|(Test|Tests|IT|TestCase)\.java$"
    r"|\.(test|spec)\.[jt]sx?$"
)


@dataclass
class AuthorHistory:
    """Repository-history features for the files and author of a change.

    Values follow the dataset's per-file averaging: `ndev`, `nuc` and `age`
    are means over the changed files of, respectively, the number of distinct
    prior authors of the file, the number of prior commits touching it, and
    the days since it was last changed (0 for a new file). `aexp` is the
    author's number of prior commits in the repository.
    """

    ndev: float
    age: float
    nuc: float
    aexp: float
    files_measured: int = 0
    source: str = "github"


@dataclass
class ChangeMetrics:
    la: int = 0
    ld: int = 0
    nf: int = 0
    nd: int = 0
    ns: int = 0
    ent: float = 0.0
    ndev: float | None = None
    age: float | None = None
    nuc: float | None = None
    aexp: float | None = None
    history_source: str = "unavailable"
    complexity_added: int = 0
    complexity_removed: int = 0
    complexity_delta: int = 0
    touches_tests: bool = False

    @property
    def history_measured(self) -> bool:
        return all(getattr(self, name) is not None for name in HISTORY_FEATURES)

    def vector(self, feature_names: list[str]) -> list[float]:
        """Feature values in the given order; unmeasured values are NaN."""
        values = asdict(self)
        return [
            float("nan") if values[name] is None else float(values[name]) for name in feature_names
        ]

    def to_dict(self) -> dict:
        return asdict(self)


def is_test_path(path: str) -> bool:
    return _TEST_PATH_RE.search(path) is not None


def change_entropy(changed_lines_per_file: list[int]) -> float:
    """Shannon entropy (base 2) of how the changed lines spread over files.

    This is the unnormalised form used by the ApacheJIT dataset: 0 for a
    single file, 1.0 for two files changed equally, log2(n) at most.
    """
    total = sum(changed_lines_per_file)
    if total <= 0:
        return 0.0
    entropy = 0.0
    for count in changed_lines_per_file:
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)
    return round(entropy, 6)


def _subsystem(path: str) -> str:
    """Top-level path component, the dataset's notion of a subsystem."""
    head, _, _ = path.partition("/")
    return head if "/" in path else "."


def compute_change_metrics(
    file_diffs: list[FileDiff],
    history: AuthorHistory | None = None,
) -> ChangeMetrics:
    """Derive the change metrics from parsed file diffs.

    Line counts cover every file in the diff, whatever its language; the
    complexity delta covers Python and Java only, because those are the
    languages the analyzers parse.
    """
    metrics = ChangeMetrics()
    changed_per_file: list[int] = []
    directories: set[str] = set()
    subsystems: set[str] = set()

    for fdiff in file_diffs:
        added = sum(len(h.added_lines) for h in fdiff.hunks)
        removed = sum(len(h.removed_lines) for h in fdiff.hunks)
        metrics.la += added
        metrics.ld += removed
        changed_per_file.append(added + removed)
        path = fdiff.path
        directories.add(posixpath.dirname(path) or ".")
        subsystems.add(_subsystem(path))
        if is_test_path(path):
            metrics.touches_tests = True

        if fdiff.language in ("python", "java"):
            post = fdiff.post_image()
            pre = fdiff.pre_image()
            metrics.complexity_added += sum(
                f.complexity
                for f in analyze_complexity(post.text, path, fdiff.language, post)
                if f.metric == "cyclomatic_complexity"
            )
            metrics.complexity_removed += sum(
                f.complexity
                for f in analyze_complexity(pre.text, path, fdiff.language, pre)
                if f.metric == "cyclomatic_complexity"
            )

    metrics.nf = len(file_diffs)
    metrics.nd = len(directories)
    metrics.ns = len(subsystems)
    metrics.ent = change_entropy(changed_per_file)
    metrics.complexity_delta = metrics.complexity_added - metrics.complexity_removed

    if history is not None:
        metrics.ndev = history.ndev
        metrics.age = history.age
        metrics.nuc = history.nuc
        metrics.aexp = history.aexp
        metrics.history_source = history.source

    return metrics
