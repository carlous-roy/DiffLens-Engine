"""Repository-history features for the risk model, from the GitHub commits API.

For the files a pull request changes, the history on the base branch gives
`age` (days since each file last changed), `nuc` (prior commits touching it)
and `ndev` (distinct prior authors), averaged over the files as in the
ApacheJIT dataset; the author's prior commits in the repository give
`aexp`. Everything is bounded: at most `max_files` files (the most changed
first), one page of 100 commits per file, and up to `AEXP_MAX_PAGES` pages
for the author. See docs/MODEL_CARD.md for the feature definitions.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.analysis.diff_parser import FileDiff
from app.github.client import GitHubClient
from app.ml.change_metrics import AuthorHistory

logger = logging.getLogger(__name__)

AEXP_MAX_PAGES = 5  # 500 commits; the model's trees split well below that


def _commit_date(commit: dict) -> datetime | None:
    raw = (commit.get("commit") or {}).get("author", {}).get("date")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _commit_author(commit: dict) -> str:
    author = commit.get("author") or {}
    if author.get("login"):
        return f"login:{author['login']}"
    email = ((commit.get("commit") or {}).get("author") or {}).get("email", "")
    return f"email:{email}"


def files_by_churn(file_diffs: list[FileDiff]) -> list[str]:
    """Changed file paths, most changed lines first."""
    churn = []
    for fdiff in file_diffs:
        lines = sum(len(h.added_lines) + len(h.removed_lines) for h in fdiff.hunks)
        churn.append((-lines, fdiff.path))
    return [path for _, path in sorted(churn)]


async def collect_author_history(
    client: GitHubClient,
    owner: str,
    repo: str,
    base_ref: str,
    file_diffs: list[FileDiff],
    author: str | None,
    until: datetime | None = None,
    max_files: int = 20,
) -> AuthorHistory | None:
    """Measure the history features, or return None when nothing could be measured.

    Files that do not exist on the base branch yet contribute 0 prior
    commits, 0 prior authors and an age of 0 days, as new files do in the
    dataset.
    """
    if max_files <= 0:
        return None
    until = until or datetime.now(UTC)
    until_iso = until.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    paths = files_by_churn(file_diffs)[:max_files]
    if not paths:
        return None

    ages, nucs, ndevs = [], [], []
    for path in paths:
        try:
            commits = await client.list_commits(
                owner, repo, sha=base_ref, path=path, until=until_iso, per_page=100
            )
        except Exception as exc:
            logger.warning("History lookup failed for %s: %s", path, exc)
            continue
        nucs.append(len(commits))
        ndevs.append(len({_commit_author(c) for c in commits}))
        dates = [d for d in (_commit_date(c) for c in commits) if d is not None]
        if dates:
            ages.append(max(0.0, (until - max(dates)).total_seconds() / 86400.0))
        else:
            ages.append(0.0)

    if not nucs:
        return None

    aexp = 0.0
    if author:
        try:
            prior = await client.list_commits(
                owner,
                repo,
                sha=base_ref,
                author=author,
                until=until_iso,
                per_page=100,
                max_pages=AEXP_MAX_PAGES,
            )
            aexp = float(len(prior))
        except Exception as exc:
            logger.warning("Author experience lookup failed for %s: %s", author, exc)

    return AuthorHistory(
        ndev=round(sum(ndevs) / len(ndevs), 4),
        age=round(sum(ages) / len(ages), 4),
        nuc=round(sum(nucs) / len(nucs), 4),
        aexp=aexp,
        files_measured=len(nucs),
        source="github",
    )
