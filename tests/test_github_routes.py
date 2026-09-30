"""Tests for the GitHub webhook and integration routes."""

import hashlib
import hmac
import json
import os
from unittest.mock import AsyncMock, patch

import pytest

from app.config import get_settings
from app.github.client import PRInfo

TEST_WEBHOOK_SECRET = "test-webhook-secret"
TEST_API_KEY = "test-api-key"

SAMPLE_PR_PAYLOAD = {
    "action": "opened",
    "pull_request": {
        "number": 7,
        "title": "Fix login bug",
        "user": {"login": "testuser"},
        "head": {"sha": "abc123def456789", "ref": "fix/login"},
        "base": {"ref": "main"},
        "html_url": "https://github.com/test/repo/pull/7",
        "created_at": "2026-09-01T10:00:00Z",
        "additions": 50,
        "deletions": 10,
        "changed_files": 3,
        "draft": False,
    },
    "repository": {"full_name": "test/repo"},
}


def _sign(body: bytes, secret: str = TEST_WEBHOOK_SECRET) -> str:
    """Build the X-Hub-Signature-256 header GitHub would send for this body."""
    digest = hmac.new(secret.encode(), msg=body, digestmod=hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _post(client, body: bytes, event: str, delivery: str | None, sign: bool = True):
    headers = {"Content-Type": "application/json", "X-GitHub-Event": event}
    if delivery is not None:
        headers["X-GitHub-Delivery"] = delivery
    if sign:
        headers["X-Hub-Signature-256"] = _sign(body)
    return client.post("/api/v1/github/webhook", content=body, headers=headers)


@pytest.fixture
def settings_env(monkeypatch):
    """Configure a webhook secret and API key for the duration of a test."""
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)
    monkeypatch.setenv("API_KEY", TEST_API_KEY)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestWebhookEndpoint:
    def test_ping_event(self, client, settings_env):
        body = json.dumps({"hook_id": 12345}).encode()
        resp = _post(client, body, "ping", "test-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "Pong" in data["message"]

    def test_irrelevant_event_skipped(self, client, settings_env):
        body = json.dumps({"action": "created"}).encode()
        resp = _post(client, body, "issues", "test-2")
        assert resp.status_code == 200
        assert resp.json()["status"] == "skipped"

    def test_pr_closed_skipped(self, client, settings_env):
        body = json.dumps({**SAMPLE_PR_PAYLOAD, "action": "closed"}).encode()
        resp = _post(client, body, "pull_request", "test-3")
        assert resp.status_code == 200
        assert resp.json()["status"] == "skipped"

    @patch("app.github.routes.analyze_pull_request", new_callable=AsyncMock)
    def test_pr_opened_queued_with_author_and_base(self, mock_analyze, client, settings_env):
        body = json.dumps(SAMPLE_PR_PAYLOAD).encode()
        resp = _post(client, body, "pull_request", "test-4")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "queued"
        assert data["pr"]["number"] == 7
        kwargs = mock_analyze.call_args.kwargs
        assert kwargs["owner"] == "test" and kwargs["repo"] == "repo"
        assert kwargs["author"] == "testuser"
        assert kwargs["base_ref"] == "main"
        assert kwargs["created_at"].isoformat() == "2026-09-01T10:00:00+00:00"

    def test_invalid_json_returns_400(self, client, settings_env):
        resp = _post(client, b"not json", "pull_request", "test-5")
        assert resp.status_code == 400

    def test_unsigned_request_rejected(self, client, settings_env):
        body = json.dumps(SAMPLE_PR_PAYLOAD).encode()
        resp = _post(client, body, "pull_request", "test-6", sign=False)
        assert resp.status_code == 401

    def test_bad_signature_rejected(self, client, settings_env):
        body = json.dumps(SAMPLE_PR_PAYLOAD).encode()
        resp = client.post(
            "/api/v1/github/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "pull_request",
                "X-GitHub-Delivery": "test-7",
                "X-Hub-Signature-256": _sign(body, secret="the-wrong-secret"),
            },
        )
        assert resp.status_code == 401

    def test_non_ascii_signature_is_rejected_not_an_error(self):
        """Servers hand header values over as latin-1 text. A non-ASCII digest
        makes `hmac.compare_digest` raise, and that must count as a bad
        signature rather than become a 500."""
        from app.github.webhook import verify_webhook_signature

        assert verify_webhook_signature(b"body", "sha256=d\u00e9adbeef", secret="s") is False

    def test_missing_delivery_id_rejected(self, client, settings_env):
        body = json.dumps({"hook_id": 1}).encode()
        assert _post(client, body, "ping", None).status_code == 400

    @patch("app.github.routes.analyze_pull_request", new_callable=AsyncMock)
    def test_replayed_delivery_rejected(self, mock_analyze, client, settings_env):
        body = json.dumps(SAMPLE_PR_PAYLOAD).encode()
        assert _post(client, body, "pull_request", "delivery-once").status_code == 200
        replay = _post(client, body, "pull_request", "delivery-once")
        assert replay.status_code == 409
        assert "already processed" in replay.json()["detail"]
        assert mock_analyze.call_count == 1
        # A new delivery id is still accepted.
        assert _post(client, body, "pull_request", "delivery-twice").status_code == 200

    @patch("app.github.routes.analyze_pull_request", new_callable=AsyncMock)
    def test_invalid_repository_name_rejected(self, mock_analyze, client, settings_env):
        payload = {**SAMPLE_PR_PAYLOAD, "repository": {"full_name": "test/evil name"}}
        body = json.dumps(payload).encode()
        resp = _post(client, body, "pull_request", "test-9")
        assert resp.status_code == 400
        assert "repository name" in resp.json()["detail"]
        mock_analyze.assert_not_called()

    @patch("app.github.routes.analyze_pull_request", new_callable=AsyncMock)
    def test_invalid_head_sha_rejected(self, mock_analyze, client, settings_env):
        payload = json.loads(json.dumps(SAMPLE_PR_PAYLOAD))
        payload["pull_request"]["head"]["sha"] = "not-a-sha"
        resp = _post(client, json.dumps(payload).encode(), "pull_request", "test-10")
        assert resp.status_code == 400
        mock_analyze.assert_not_called()


class TestAnalyzePrRoute:
    def test_disabled_until_api_key_configured(self, client):
        resp = client.post(
            "/api/v1/github/analyze-pr", json={"owner": "o", "repo": "r", "number": 1}
        )
        assert resp.status_code == 503

    def test_requires_api_key(self, client, settings_env):
        resp = client.post(
            "/api/v1/github/analyze-pr", json={"owner": "o", "repo": "r", "number": 1}
        )
        assert resp.status_code == 401
        resp = client.post(
            "/api/v1/github/analyze-pr",
            json={"owner": "o", "repo": "r", "number": 1},
            headers={"X-API-Key": "wrong"},
        )
        assert resp.status_code == 401

    def test_rejects_invalid_names(self, client, settings_env):
        resp = client.post(
            "/api/v1/github/analyze-pr",
            json={"owner": "o/../x", "repo": "r", "number": 1},
            headers={"X-API-Key": TEST_API_KEY},
        )
        assert resp.status_code == 422
        resp = client.post(
            "/api/v1/github/analyze-pr",
            json={"owner": "o", "repo": "r", "number": 0},
            headers={"X-API-Key": TEST_API_KEY},
        )
        assert resp.status_code == 422

    def test_needs_a_github_token(self, client, settings_env):
        resp = client.post(
            "/api/v1/github/analyze-pr",
            json={"owner": "o", "repo": "r", "number": 1},
            headers={"X-API-Key": TEST_API_KEY},
        )
        assert resp.status_code == 400
        assert "token" in resp.json()["detail"].lower()

    @patch("app.github.routes.analyze_pull_request", new_callable=AsyncMock)
    @patch("app.github.routes.GitHubClient.get_pr", new_callable=AsyncMock)
    def test_queues_analysis_with_pr_metadata(
        self, mock_get_pr, mock_analyze, client, settings_env
    ):
        mock_get_pr.return_value = PRInfo(
            owner="o",
            repo="r",
            number=3,
            head_sha="a" * 40,
            title="T",
            author="alice",
            base_ref="develop",
            head_ref="feature",
            html_url="https://github.com/o/r/pull/3",
        )
        resp = client.post(
            "/api/v1/github/analyze-pr",
            json={"owner": "o", "repo": "r", "number": 3, "token": "ghp_x"},
            headers={"X-API-Key": TEST_API_KEY},
        )
        assert resp.status_code == 200
        assert resp.json()["pr"]["author"] == "alice"
        kwargs = mock_analyze.call_args.kwargs
        assert kwargs["author"] == "alice"
        assert kwargs["base_ref"] == "develop"
        assert kwargs["token"] == "ghp_x"


class TestGitHubStatus:
    def test_status_without_token(self, client):
        resp = client.get("/api/v1/github/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is False
        assert data["api_key_set"] is False
        assert "authenticated_as" not in data

    def test_status_features_listed(self, client):
        data = client.get("/api/v1/github/status").json()
        assert "features" in data
        assert "post_comment" in data["features"]
        assert "post_review" in data["features"]
        assert "history_features" in data["features"]

    def test_status_with_token_verifies_once(self, client, monkeypatch):
        """The stubbed `verify_token` is called once and then cached."""
        from app.github import routes

        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_not_a_real_token")
        get_settings.cache_clear()
        routes._identity_cache.update(token=None, checked_at=0.0)
        calls = {"n": 0}

        async def counting_verify(self):
            calls["n"] += 1
            return {"login": "difflens-test-bot"}

        monkeypatch.setattr(routes.GitHubClient, "verify_token", counting_verify)
        try:
            first = client.get("/api/v1/github/status").json()
            second = client.get("/api/v1/github/status").json()
        finally:
            get_settings.cache_clear()
            routes._identity_cache.update(token=None, checked_at=0.0)
        assert first["configured"] is True
        assert first["authenticated_as"] == "difflens-test-bot"
        assert second["authenticated_as"] == "difflens-test-bot"
        assert calls["n"] == 1


class TestListPrs:
    def test_limit_is_bounded(self, client):
        assert client.get("/api/v1/github/prs?limit=0").status_code == 422
        assert client.get("/api/v1/github/prs?limit=1000").status_code == 422
        assert client.get("/api/v1/github/prs?limit=5").status_code == 200


class TestHermeticEnvironment:
    def test_ambient_github_credentials_are_not_read(self):
        """conftest strips GITHUB_TOKEN/GH_TOKEN before settings load."""
        assert "GITHUB_TOKEN" not in os.environ
        assert "GH_TOKEN" not in os.environ
        assert get_settings().github_token is None
