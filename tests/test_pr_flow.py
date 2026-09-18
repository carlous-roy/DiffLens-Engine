"""End-to-end tests of the pull request flow against a fake GitHub API.

Nothing here touches the network: `FakeGitHub` answers through an httpx
mock transport and the database is the per-test SQLite session factory.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.config import get_settings
from app.db.models import AnalysisFinding, AnalysisRun, GitHubPR
from app.github.client import GitHubClient
from app.github.formatter import SUMMARY_MARKER
from app.github.pr_analyzer import analyze_pull_request
from tests.fake_github import FakeGitHub

HEAD_SHA = "f" * 40

# A modified file whose hunks start at new-file lines 100 and 150: the inline
# comments only land if line numbers are mapped through the hunk headers.
RISKY_DIFF = "\n".join(
    [
        "diff --git a/pkg/service.py b/pkg/service.py",
        "--- a/pkg/service.py",
        "+++ b/pkg/service.py",
        "@@ -95,7 +100,13 @@ class Service:",
        "     def existing(self):",
        "         return 1",
        " ",
        "+    def route(self, x, cache={}):",
        "+        if x:",
        "+            return eval(x)",
        "+        exec(x)",
        "+        return 'eval(z) in a string'",
        "+",
        "     def other(self):",
        "         return 2",
        "@@ -140,4 +150,4 @@ class Service:",
        "     def last(self):",
        "-        return old_value",
        "+        return eval(new_value)",
        "",
    ]
)

CLEAN_DIFF = "\n".join(
    [
        "diff --git a/pkg/util.py b/pkg/util.py",
        "--- a/pkg/util.py",
        "+++ b/pkg/util.py",
        "@@ -10,3 +10,6 @@",
        " x = 1",
        "+",
        "+def add(a, b):",
        "+    return a + b",
        " y = 2",
        "",
    ]
)


def _commit(sha: str, login: str, days_ago: int) -> dict:
    date = (datetime(2026, 9, 1, tzinfo=UTC) - timedelta(days=days_ago)).isoformat()
    return {
        "sha": sha,
        "author": {"login": login},
        "commit": {"author": {"email": f"{login}@example.com", "date": date}},
    }


@pytest.fixture
def github_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_not_a_real_token")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _fake(diff=RISKY_DIFF, **kwargs) -> FakeGitHub:
    kwargs.setdefault(
        "commits",
        {
            "pkg/service.py": [
                _commit("1" * 40, "bob", 3),
                _commit("2" * 40, "carol", 30),
                _commit("3" * 40, "bob", 90),
            ]
        },
    )
    kwargs.setdefault("author_commits", [_commit(str(i) * 40, "alice", i) for i in range(4, 12)])
    return FakeGitHub(diff, **kwargs)


async def _run(fake: FakeGitHub, session_factory, **overrides) -> dict:
    params = {
        "owner": "acme",
        "repo": "widgets",
        "number": 7,
        "head_sha": HEAD_SHA,
        "action": "opened",
        "author": "alice",
        "base_ref": "main",
        "created_at": datetime(2026, 9, 1, tzinfo=UTC),
        "client": GitHubClient(token="ghp_test", transport=fake.transport),
        "session_factory": session_factory,
    }
    params.update(overrides)
    return await analyze_pull_request(**params)


class TestFirstRun:
    async def test_posts_status_comment_and_inline_review(
        self, client, session_factory, github_env
    ):
        fake = _fake()
        info = await _run(fake, session_factory)

        assert info["status"] == "completed"
        assert info["history_measured"] is True

        # Commit statuses: pending first, then the final state.
        assert [s["state"] for s in fake.statuses] == ["pending", "failure"]
        assert "Risk: HIGH" in fake.statuses[-1]["description"]

        # The diff was fetched with the diff media type, exactly once.
        diff_calls = [
            r for r in fake.calls("GET", r"/pulls/7$") if "diff" in r.headers.get("Accept", "")
        ]
        assert len(diff_calls) == 1

        # History: one commits listing per changed file plus one for the author.
        history_calls = fake.calls("GET", r"/commits$")
        assert len(history_calls) == 2
        assert b"path=pkg%2Fservice.py" in history_calls[0].url.query
        assert b"author=alice" in history_calls[1].url.query
        assert b"until=2026-09-01T00%3A00%3A00Z" in history_calls[1].url.query

        # One summary comment, created (no earlier one), carrying the marker.
        assert len(fake.calls("POST", r"/issues/7/comments$")) == 1
        assert fake.calls("PATCH") == []
        body = fake.comments[100]["body"]
        assert body.startswith(SUMMARY_MARKER)
        assert "DiffLens Code Review" in body
        assert "`pkg/service.py:105`" in body

        # The review requested changes (another author) with inline comments
        # at real new-file line numbers, which the fake GitHub validated.
        assert len(fake.reviews) == 1
        review = fake.reviews[0]
        assert review["event"] == "REQUEST_CHANGES"
        lines = sorted((c["path"], c["line"]) for c in review["comments"])
        assert lines == [
            ("pkg/service.py", 103),
            ("pkg/service.py", 105),
            ("pkg/service.py", 106),
            ("pkg/service.py", 151),
        ]

        # Persisted: the run, its findings with embeddings, and the PR record
        # remembering the comment id.
        db = session_factory()
        try:
            run = db.query(AnalysisRun).one()
            assert str(run.id) == info["run_id"]
            assert run.source == "github"
            assert run.risk["model_type"] == "gradient_boosting"
            assert run.risk["model_version"].endswith("/full")
            assert run.risk["features"]["aexp"] == 8.0
            pr = db.query(GitHubPR).one()
            assert (pr.owner, pr.repo, pr.pr_number, pr.comment_id) == ("acme", "widgets", 7, 100)
            findings = db.query(AnalysisFinding).all()
            assert findings and all(f.embedding is not None for f in findings)
        finally:
            db.close()

    async def test_history_features_are_averaged_per_file(
        self, client, session_factory, github_env
    ):
        fake = _fake()
        info = await _run(fake, session_factory)
        db = session_factory()
        try:
            features = db.query(AnalysisRun).one().risk["features"]
        finally:
            db.close()
        assert info["history_measured"] is True
        assert features["nuc"] == 3.0  # three prior commits on the one changed file
        assert features["ndev"] == 2.0  # bob and carol
        assert features["age"] == 3.0  # newest prior commit was three days before
        assert features["history_source"] == "github"


class TestRepeatRuns:
    async def test_second_push_updates_the_existing_comment(
        self, client, session_factory, github_env
    ):
        fake = _fake()
        await _run(fake, session_factory)
        await _run(fake, session_factory, action="synchronize")

        assert len(fake.calls("POST", r"/issues/7/comments$")) == 1
        patches = fake.calls("PATCH", r"/issues/comments/100$")
        assert len(patches) == 1
        assert len(fake.comments) == 1
        # The second run's persisted PR row also points at the same comment.
        db = session_factory()
        try:
            rows = db.query(GitHubPR).order_by(GitHubPR.created_at).all()
            assert [r.action for r in rows] == ["opened", "synchronize"]
            assert {r.comment_id for r in rows} == {100}
        finally:
            db.close()

    async def test_existing_comment_found_by_marker(self, client, session_factory, github_env):
        """A comment from before the database knew about it is found by its marker."""
        fake = _fake(
            existing_comments=[
                {
                    "id": 55,
                    "body": f"{SUMMARY_MARKER}\nold summary",
                    "user": {"login": "difflens-bot"},
                },
                {"id": 56, "body": "human comment", "user": {"login": "alice"}},
            ]
        )
        await _run(fake, session_factory)
        assert len(fake.calls("PATCH", r"/issues/comments/55$")) == 1
        assert fake.calls("POST", r"/issues/7/comments$") == []
        assert "DiffLens Code Review" in fake.comments[55]["body"]

    async def test_deleted_comment_falls_back_to_a_new_one(
        self, client, session_factory, github_env
    ):
        fake = _fake()
        await _run(fake, session_factory)
        fake.deleted_comment_ids.add(100)
        await _run(fake, session_factory, action="synchronize")
        assert len(fake.calls("PATCH", r"/issues/comments/100$")) == 1
        assert len(fake.calls("POST", r"/issues/7/comments$")) == 2
        db = session_factory()
        try:
            latest = db.query(GitHubPR).order_by(GitHubPR.created_at.desc()).first()
            assert latest.comment_id == 101
        finally:
            db.close()


class TestReviewEvent:
    async def test_own_pull_request_gets_a_comment_not_request_changes(
        self, client, session_factory, github_env
    ):
        # conftest stubs `verify_token` to return "difflens-test-bot".
        fake = _fake(author="difflens-test-bot")
        await _run(fake, session_factory, author="difflens-test-bot")
        assert fake.reviews[0]["event"] == "COMMENT"

    async def test_low_risk_is_a_comment(self, client, session_factory, github_env):
        fake = _fake(diff=CLEAN_DIFF, commits={"pkg/util.py": []})
        info = await _run(fake, session_factory)
        assert info["status"] == "completed"
        assert fake.statuses[-1]["state"] == "success"
        # Only info-level findings: no inline review is posted.
        assert fake.reviews == []


class TestGuards:
    async def test_oversized_diff_is_skipped(
        self, client, session_factory, github_env, monkeypatch
    ):
        monkeypatch.setenv("MAX_DIFF_BYTES", "50")
        get_settings.cache_clear()
        fake = _fake()
        info = await _run(fake, session_factory)
        assert info["status"] == "skipped"
        assert "above the 50 byte limit" in info["error"]
        assert fake.statuses[-1]["state"] == "error"
        assert fake.calls("POST", r"/comments$") == []

    async def test_history_lookups_can_be_disabled(
        self, client, session_factory, github_env, monkeypatch
    ):
        monkeypatch.setenv("GITHUB_HISTORY_MAX_FILES", "0")
        get_settings.cache_clear()
        fake = _fake()
        info = await _run(fake, session_factory)
        assert info["history_measured"] is False
        assert fake.calls("GET", r"/commits$") == []
        db = session_factory()
        try:
            assert db.query(AnalysisRun).one().risk["model_version"].endswith("/diff_only")
        finally:
            db.close()

    async def test_history_failure_is_not_fatal(self, client, session_factory, github_env):
        fake = _fake()
        original = fake.handler

        def failing(request):
            if request.url.path.endswith("/commits"):
                import httpx

                return httpx.Response(500, json={"message": "boom"})
            return original(request)

        fake.handler = failing
        import httpx

        client_ = GitHubClient(token="ghp_test", transport=httpx.MockTransport(failing))
        info = await _run(fake, session_factory, client=client_)
        assert info["status"] == "completed"
        assert info["history_measured"] is False

    async def test_invalid_names_are_refused_before_any_request(
        self, client, session_factory, github_env
    ):
        fake = _fake()
        info = await _run(fake, session_factory, owner="bad owner")
        assert info["status"] == "error"
        assert "Invalid owner" in info["error"]
        assert fake.requests == []

        info = await _run(fake, session_factory, head_sha="not-hex")
        assert info["status"] == "error"
        assert fake.requests == []

    async def test_diff_fetch_failure_sets_error_status(self, client, session_factory, github_env):
        import httpx

        def handler(request):
            if "diff" in request.headers.get("Accept", ""):
                return httpx.Response(502, text="bad gateway")
            return httpx.Response(201, json={})

        client_ = GitHubClient(token="ghp_test", transport=httpx.MockTransport(handler))
        info = await _run(_fake(), session_factory, client=client_)
        assert info["status"] == "error"
        assert "Failed to fetch diff" not in json.dumps(info)  # error text is the exception
        assert "502" in info["error"]


class TestSmartReviewOnPullRequests:
    async def test_stub_provider_review_is_posted(
        self, client, session_factory, github_env, monkeypatch
    ):
        from app.ml import llm_provider

        monkeypatch.setenv("LLM_PROVIDER", "stub")
        monkeypatch.setenv("GITHUB_ENABLE_SMART_REVIEW", "true")
        get_settings.cache_clear()
        llm_provider._provider = None
        try:
            fake = _fake()
            info = await _run(fake, session_factory)
        finally:
            llm_provider._provider = None
        assert info["status"] == "completed"
        body = fake.comments[100]["body"]
        assert "LLM Review" in body
        assert "Stub provider response" in body
