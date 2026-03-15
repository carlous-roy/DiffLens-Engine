"""Tests for GitHub webhook API routes."""
import hashlib
import hmac
import json
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

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

def _sign_payload(payload: dict, secret: str = "") -> str:
    body = json.dumps(payload).encode()
    if not secret:
        return ""
    digest = hmac.new(secret.encode(), msg=body, digestmod=hashlib.sha256).hexdigest()
    return f"sha256={digest}"

class TestWebhookEndpoint:
    def test_ping_event(self):
        resp = client.post(
            "/api/v1/github/webhook",
            json={"hook_id": 12345},
            headers={"X-GitHub-Event": "ping", "X-GitHub-Delivery": "test-1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "Pong" in data["message"]

    def test_irrelevant_event_skipped(self):
        resp = client.post(
            "/api/v1/github/webhook",
            json={"action": "created"},
            headers={"X-GitHub-Event": "issues", "X-GitHub-Delivery": "test-2"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "skipped"

    def test_pr_closed_skipped(self):
        payload = {**SAMPLE_PR_PAYLOAD, "action": "closed"}
        resp = client.post(
            "/api/v1/github/webhook",
            json=payload,
            headers={"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "test-3"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "skipped"

    @patch("app.github.routes.analyze_pull_request", new_callable=AsyncMock)
    def test_pr_opened_queued(self, mock_analyze):
        resp = client.post(
            "/api/v1/github/webhook",
            json=SAMPLE_PR_PAYLOAD,
            headers={
                "X-GitHub-Event": "pull_request",
                "X-GitHub-Delivery": "test-4",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "queued"
        assert data["pr"]["number"] == 7

    def test_invalid_json_returns_400(self):
        resp = client.post(
            "/api/v1/github/webhook",
            content=b"not json",
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "pull_request",
                "X-GitHub-Delivery": "test-5",
            },
        )
        assert resp.status_code == 400

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
