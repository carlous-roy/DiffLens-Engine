"""Tests for GitHub webhook API routes."""
import hashlib
import hmac
import json
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

client = TestClient(app)

TEST_WEBHOOK_SECRET = "test-webhook-secret"

SAMPLE_PR_PAYLOAD = {
    "action": "opened",
    "pull_request": {
        "number": 7,
        "title": "Fix login bug",
        "user": {"login": "testuser"},
        "head": {"sha": "abc123def456789", "ref": "fix/login"},
        "base": {"ref": "main"},
        "html_url": "https://github.com/test/repo/pull/7",
        "additions": 50,
        "deletions": 10,
        "changed_files": 3,
        "draft": False,
    },
    "repository": {
        "full_name": "test/repo",
    },
}

def _sign(body: bytes, secret: str = TEST_WEBHOOK_SECRET) -> str:
    """Build the X-Hub-Signature-256 header GitHub would send for this body."""
    digest = hmac.new(secret.encode(), msg=body, digestmod=hashlib.sha256).hexdigest()
    return f"sha256={digest}"

def _post(body: bytes, event: str, delivery: str, sign: bool = True):
    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": delivery,
    }
    if sign:
        headers["X-Hub-Signature-256"] = _sign(body)
    return client.post("/api/v1/github/webhook", content=body, headers=headers)

class TestWebhookEndpoint:
    @pytest.fixture(autouse=True)
    def _configure_secret(self, monkeypatch):
        """The endpoint fails closed, so every request must be signed."""
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    def test_ping_event(self):
        body = json.dumps({"hook_id": 12345}).encode()
        resp = _post(body, "ping", "test-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "Pong" in data["message"]

    def test_irrelevant_event_skipped(self):
        body = json.dumps({"action": "created"}).encode()
        resp = _post(body, "issues", "test-2")
        assert resp.status_code == 200
        assert resp.json()["status"] == "skipped"

    def test_pr_closed_skipped(self):
        body = json.dumps({**SAMPLE_PR_PAYLOAD, "action": "closed"}).encode()
        resp = _post(body, "pull_request", "test-3")
        assert resp.status_code == 200
        assert resp.json()["status"] == "skipped"

    @patch("app.github.routes.analyze_pull_request", new_callable=AsyncMock)
    def test_pr_opened_queued(self, mock_analyze):
        body = json.dumps(SAMPLE_PR_PAYLOAD).encode()
        resp = _post(body, "pull_request", "test-4")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "queued"
        assert data["pr"]["number"] == 7

    def test_invalid_json_returns_400(self):
        resp = _post(b"not json", "pull_request", "test-5")
        assert resp.status_code == 400

    def test_unsigned_request_rejected(self):
        body = json.dumps(SAMPLE_PR_PAYLOAD).encode()
        resp = _post(body, "pull_request", "test-6", sign=False)
        assert resp.status_code == 401

    def test_bad_signature_rejected(self):
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

class TestGitHubStatus:
    def test_status_without_token(self):
        resp = client.get("/api/v1/github/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is False

    def test_status_features_listed(self):
        resp = client.get("/api/v1/github/status")
        data = resp.json()
        assert "features" in data
        assert "post_comment" in data["features"]
        assert "post_review" in data["features"]
