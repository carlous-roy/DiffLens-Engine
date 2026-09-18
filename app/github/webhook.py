"""GitHub webhook handler — receives, verifies, and dispatches webhook events."""

import hashlib
import hmac
import logging

from app.config import get_settings

logger = logging.getLogger(__name__)


def verify_webhook_signature(
    payload_body: bytes,
    signature_header: str | None,
    secret: str | None = None,
) -> bool:
    """Verify the GitHub webhook signature (HMAC SHA-256)."""
    settings = get_settings()
    webhook_secret = secret or settings.github_webhook_secret

    if not webhook_secret:
        logger.error(
            "GITHUB_WEBHOOK_SECRET is not configured; rejecting the webhook "
            "delivery. Set GITHUB_WEBHOOK_SECRET to the value configured on "
            "the GitHub webhook to enable signature verification."
        )
        return False

    if not signature_header:
        logger.warning("No X-Hub-Signature-256 header present.")
        return False

    # Extract the hex digest from "sha256=<digest>"
    if not signature_header.startswith("sha256="):
        logger.warning("Signature header does not start with sha256=")
        return False

    expected_signature = signature_header[7:]  # strip "sha256="

    # Compute HMAC
    mac = hmac.new(
        webhook_secret.encode("utf-8"),
        msg=payload_body,
        digestmod=hashlib.sha256,
    )
    computed = mac.hexdigest()

    # Constant-time comparison to prevent timing attacks. A header with
    # non-ASCII characters makes compare_digest raise; that is a bad
    # signature, not a server error.
    try:
        return hmac.compare_digest(computed, expected_signature)
    except TypeError:
        logger.warning("Signature header is not a valid hex digest.")
        return False


SUPPORTED_EVENTS = {"pull_request", "ping"}

PR_ACTIONS_TO_ANALYZE = {"opened", "synchronize", "reopened"}


def should_analyze_event(event_type: str, payload: dict) -> bool:
    """Determine whether a webhook event should trigger DiffLens analysis."""
    if event_type == "ping":
        logger.info("Received GitHub ping event — webhook is configured correctly.")
        return False

    if event_type != "pull_request":
        logger.debug(f"Ignoring event type: {event_type}")
        return False

    action = payload.get("action", "")
    if action not in PR_ACTIONS_TO_ANALYZE:
        logger.debug(f"Ignoring PR action: {action}")
        return False

    # Skip draft PRs unless configured otherwise
    pr = payload.get("pull_request", {})
    if pr.get("draft", False):
        settings = get_settings()
        if not settings.github_analyze_drafts:
            logger.debug("Skipping draft PR.")
            return False

    return True


def extract_pr_info(payload: dict) -> dict:
    """Extract essential PR info from a webhook payload."""
    pr = payload.get("pull_request") or {}
    repo = payload.get("repository") or {}

    owner_repo = (repo.get("full_name") or "").split("/")
    owner = owner_repo[0] if len(owner_repo) == 2 else ""
    repo_name = owner_repo[1] if len(owner_repo) == 2 else ""

    return {
        "owner": owner,
        "repo": repo_name,
        "number": pr.get("number"),
        "head_sha": (pr.get("head") or {}).get("sha", ""),
        "title": pr.get("title", ""),
        "author": (pr.get("user") or {}).get("login", ""),
        "base_ref": (pr.get("base") or {}).get("ref", ""),
        "head_ref": (pr.get("head") or {}).get("ref", ""),
        "html_url": pr.get("html_url", ""),
        "created_at": pr.get("created_at"),
        "additions": pr.get("additions", 0),
        "deletions": pr.get("deletions", 0),
        "changed_files": pr.get("changed_files", 0),
        "action": payload.get("action", ""),
    }


def validate_pr_info(info: dict) -> str | None:
    """Return a reason the payload cannot be acted on, or None when it is sound."""
    from app.github.client import NAME_RE, SHA_RE

    if not NAME_RE.match(info.get("owner") or ""):
        return "repository owner is missing or invalid"
    if not NAME_RE.match(info.get("repo") or ""):
        return "repository name is missing or invalid"
    if not isinstance(info.get("number"), int) or info["number"] < 1:
        return "pull request number is missing or invalid"
    if not SHA_RE.match(info.get("head_sha") or ""):
        return "head sha is missing or invalid"
    return None
