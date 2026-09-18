"""GitHub webhook and integration API routes."""

import logging
import time
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import require_api_key
from app.config import get_settings
from app.db import get_db
from app.db.models import AnalysisRun, GitHubPR, WebhookDelivery
from app.github.client import GitHubClient
from app.github.pr_analyzer import analyze_pull_request
from app.github.webhook import (
    extract_pr_info,
    should_analyze_event,
    validate_pr_info,
    verify_webhook_signature,
)

logger = logging.getLogger(__name__)

github_router = APIRouter(prefix="/github", tags=["github"])

NAME_PATTERN = r"^[A-Za-z0-9_.-]+$"
IDENTITY_TTL_SECONDS = 3600


@github_router.post("/webhook")
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Receive and process GitHub webhook events."""
    # Read raw body for signature verification
    body = await request.body()

    # Verify signature
    signature = request.headers.get("X-Hub-Signature-256")
    if not verify_webhook_signature(body, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature.")

    # Parse event
    event_type = request.headers.get("X-GitHub-Event", "unknown")
    delivery_id = request.headers.get("X-GitHub-Delivery")
    if not delivery_id or len(delivery_id) > 100:
        raise HTTPException(status_code=400, detail="Missing X-GitHub-Delivery header.")

    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.") from e
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    # Record the delivery id; a repeat of one already seen is a replay.
    db.add(WebhookDelivery(delivery_id=delivery_id, event=event_type))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        logger.warning("Rejected replayed webhook delivery %s", delivery_id)
        raise HTTPException(
            status_code=409, detail=f"Delivery {delivery_id} was already processed."
        ) from None

    logger.info("Webhook received: event=%s, delivery=%s", event_type, delivery_id)

    # Handle ping (webhook setup confirmation)
    if event_type == "ping":
        return {
            "status": "ok",
            "message": "Pong! DiffLens webhook is configured.",
            "hook_id": payload.get("hook_id"),
        }

    # Check if we should analyze this event
    if not should_analyze_event(event_type, payload):
        return {
            "status": "skipped",
            "message": f"Event type '{event_type}' with action "
            f"'{payload.get('action', 'n/a')}' does not require analysis.",
        }

    # Extract PR info and queue analysis
    pr_info = extract_pr_info(payload)
    problem = validate_pr_info(pr_info)
    if problem:
        raise HTTPException(status_code=400, detail=f"Cannot analyze this payload: {problem}.")
    logger.info(
        "Queueing analysis for %s/%s#%s (%s)",
        pr_info["owner"],
        pr_info["repo"],
        pr_info["number"],
        pr_info["action"],
    )

    background_tasks.add_task(
        analyze_pull_request,
        owner=pr_info["owner"],
        repo=pr_info["repo"],
        number=pr_info["number"],
        head_sha=pr_info["head_sha"],
        action=pr_info["action"],
        author=pr_info["author"] or None,
        base_ref=pr_info["base_ref"] or None,
        created_at=_parse_timestamp(pr_info.get("created_at")),
    )

    return {
        "status": "queued",
        "message": f"Analysis queued for PR #{pr_info['number']}",
        "pr": {
            "repo": f"{pr_info['owner']}/{pr_info['repo']}",
            "number": pr_info["number"],
            "sha": pr_info["head_sha"][:8],
        },
    }


def _parse_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


class AnalyzePRRequest(BaseModel):
    """Request to manually analyze a GitHub PR."""

    owner: str = Field(
        ..., pattern=NAME_PATTERN, max_length=100, description="Repository owner (user or org)"
    )
    repo: str = Field(..., pattern=NAME_PATTERN, max_length=100, description="Repository name")
    number: int = Field(..., ge=1, description="PR number")
    token: str | None = Field(None, max_length=255, description="GitHub token override (optional)")


@github_router.post("/analyze-pr", dependencies=[Depends(require_api_key)])
async def trigger_pr_analysis(
    request: AnalyzePRRequest,
    background_tasks: BackgroundTasks,
):
    """Manually trigger DiffLens analysis on a GitHub PR. Requires the API key."""
    settings = get_settings()
    token = request.token or settings.github_token
    if not token:
        raise HTTPException(
            status_code=400,
            detail="GitHub token required. Set GITHUB_TOKEN or pass 'token' in request.",
        )

    # Fetch PR to get head SHA
    try:
        client = GitHubClient(token=token)
        pr = await client.get_pr(request.owner, request.repo, request.number)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch PR: {e}") from e

    background_tasks.add_task(
        analyze_pull_request,
        owner=request.owner,
        repo=request.repo,
        number=request.number,
        head_sha=pr.head_sha,
        action="manual",
        token=token,
        author=pr.author,
        base_ref=pr.base_ref,
    )

    return {
        "status": "queued",
        "message": f"Analysis queued for {request.owner}/{request.repo}#{request.number}",
        "pr": {
            "title": pr.title,
            "author": pr.author,
            "sha": pr.head_sha[:8],
        },
    }


_identity_cache: dict = {"login": None, "error": None, "checked_at": 0.0, "token": None}


async def token_identity() -> dict:
    """Login of the configured token, verified at most once an hour.

    Every status request used to call GitHub; the result is now cached so
    the dashboard cannot burn the token's rate limit.
    """
    settings = get_settings()
    if not settings.github_token:
        return {}
    fresh = (
        _identity_cache["token"] == settings.github_token
        and time.monotonic() - _identity_cache["checked_at"] < IDENTITY_TTL_SECONDS
    )
    if not fresh:
        _identity_cache.update(token=settings.github_token, checked_at=time.monotonic())
        try:
            user = await GitHubClient().verify_token()
            _identity_cache.update(login=user.get("login"), error=None)
        except Exception as e:
            _identity_cache.update(login=None, error=str(e))
    if _identity_cache["error"]:
        return {"token_error": _identity_cache["error"]}
    return {"authenticated_as": _identity_cache["login"], "token_verified": True}


@github_router.get("/status")
async def github_status():
    """Check the status of GitHub integration."""
    settings = get_settings()

    status = {
        "configured": bool(settings.github_token),
        "webhook_secret_set": bool(settings.github_webhook_secret),
        "api_key_set": bool(settings.api_key),
        "features": {
            "post_comment": settings.github_post_comment,
            "post_review": settings.github_post_review,
            "use_checks_api": settings.github_use_checks_api,
            "analyze_drafts": settings.github_analyze_drafts,
            "smart_review_on_prs": settings.github_enable_smart_review,
            "history_features": settings.github_history_max_files > 0,
        },
        "public_url": settings.app_public_url,
    }
    status.update(await token_identity())
    return status


@github_router.get("/prs")
def list_analyzed_prs(
    limit: int = Query(20, ge=1, le=200),
    repo: str | None = Query(None, max_length=201),
    db: Session = Depends(get_db),
):
    """List GitHub PRs that have been analyzed by DiffLens."""
    query = db.query(GitHubPR).join(AnalysisRun).order_by(GitHubPR.created_at.desc())

    if repo:
        # Filter by "owner/repo" format
        parts = repo.split("/")
        if len(parts) == 2:
            query = query.filter(GitHubPR.owner == parts[0], GitHubPR.repo == parts[1])

    prs = query.limit(limit).all()

    return [
        {
            "id": str(pr.id),
            "run_id": str(pr.run_id),
            "owner": pr.owner,
            "repo": pr.repo,
            "pr_number": pr.pr_number,
            "head_sha": pr.head_sha,
            "action": pr.action,
            "pr_url": pr.pr_url,
            "comment_id": pr.comment_id,
            "created_at": pr.created_at.isoformat() if pr.created_at else None,
            "summary": pr.run.summary if pr.run else None,
            "risk_level": (pr.run.risk or {}).get("level") if pr.run and pr.run.risk else None,
        }
        for pr in prs
    ]
