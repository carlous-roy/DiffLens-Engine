"""Tests for GitHub webhook verification and event dispatch."""
import hashlib
import hmac

from app.github.webhook import (
    verify_webhook_signature,
    should_analyze_event,
    extract_pr_info,
    PR_ACTIONS_TO_ANALYZE,
)

class TestWebhookSignature:
    def test_valid_signature(self):
        secret = "webhook-test-value"
        payload = b'{"action": "opened"}'
        digest = hmac.new(
            secret.encode(), msg=payload, digestmod=hashlib.sha256
        ).hexdigest()
        signature = f"sha256={digest}"

        assert verify_webhook_signature(payload, signature, secret=secret) is True

    def test_invalid_signature(self):
        secret = "webhook-test-value"
        payload = b'{"action": "opened"}'
        assert verify_webhook_signature(
            payload, "sha256=deadbeef", secret=secret
        ) is False

    def test_missing_signature_with_secret(self):
        assert verify_webhook_signature(
            b"body", None, secret="webhook-test-value"
        ) is False

    def test_no_secret_configured_rejects(self):
        """Fail closed: with no secret configured nothing can be verified."""
        assert verify_webhook_signature(
            b"anything", "sha256=whatever", secret=None
        ) is False

    def test_wrong_prefix(self):
        assert verify_webhook_signature(
            b"body", "sha1=abc123", secret="webhook-test-value"
        ) is False

class TestShouldAnalyze:
    def test_ping_event(self):
        assert should_analyze_event("ping", {}) is False

    def test_pr_opened(self):
        payload = {"action": "opened", "pull_request": {"draft": False}}
        assert should_analyze_event("pull_request", payload) is True

    def test_pr_synchronize(self):
        payload = {"action": "synchronize", "pull_request": {"draft": False}}
        assert should_analyze_event("pull_request", payload) is True

    def test_pr_reopened(self):
        payload = {"action": "reopened", "pull_request": {"draft": False}}
        assert should_analyze_event("pull_request", payload) is True

    def test_pr_closed_ignored(self):
        payload = {"action": "closed", "pull_request": {}}
        assert should_analyze_event("pull_request", payload) is False

    def test_pr_labeled_ignored(self):
        payload = {"action": "labeled", "pull_request": {}}
        assert should_analyze_event("pull_request", payload) is False

    def test_push_event_ignored(self):
        assert should_analyze_event("push", {}) is False

    def test_issues_event_ignored(self):
        assert should_analyze_event("issues", {"action": "opened"}) is False

    def test_draft_pr_skipped(self):
        payload = {"action": "opened", "pull_request": {"draft": True}}
        # Default setting: analyze_drafts = False
        assert should_analyze_event("pull_request", payload) is False

SAMPLE_WEBHOOK_PAYLOAD = {
    "action": "opened",
    "pull_request": {
        "number": 42,
        "title": "Add feature X",
        "user": {"login": "dev-user"},
        "head": {"sha": "abc123def456", "ref": "feature/x"},
        "base": {"ref": "main"},
        "html_url": "https://github.com/acme/repo/pull/42",
        "additions": 120,
        "deletions": 30,
        "changed_files": 5,
        "draft": False,
    },
    "repository": {
        "full_name": "acme/repo",
    },
}

class TestExtractPRInfo:
    def test_extracts_all_fields(self):
        info = extract_pr_info(SAMPLE_WEBHOOK_PAYLOAD)
        assert info["owner"] == "acme"
        assert info["repo"] == "repo"
        assert info["number"] == 42
        assert info["head_sha"] == "abc123def456"
        assert info["title"] == "Add feature X"
        assert info["author"] == "dev-user"
        assert info["base_ref"] == "main"
        assert info["head_ref"] == "feature/x"
        assert info["html_url"] == "https://github.com/acme/repo/pull/42"
        assert info["additions"] == 120
        assert info["deletions"] == 30
        assert info["changed_files"] == 5
        assert info["action"] == "opened"

    def test_handles_missing_fields_gracefully(self):
        minimal = {
            "action": "opened",
            "pull_request": {"head": {}, "base": {}, "user": {}},
            "repository": {"full_name": ""},
        }
        info = extract_pr_info(minimal)
        assert info["owner"] == ""
        assert info["repo"] == ""
        assert info["number"] is None
        assert info["head_sha"] == ""
