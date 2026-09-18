"""GitHub webhook and integration API routes."""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.db.models import AnalysisRun, GitHubPR
from app.github.client import GitHubClient
from app.github.pr_analyzer import analyze_pull_request
from app.github.webhook import (
    extract_pr_info,
    should_analyze_event,
    verify_webhook_signature,
)

logger = logging.getLogger(__name__)

github_router = APIRouter(prefix="/github", tags=["github"])


@github_router.post("/webhook")
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
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
    delivery_id = request.headers.get("X-GitHub-Delivery", "unknown")

    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.") from e

    logger.info(f"Webhook received: event={event_type}, delivery={delivery_id}")

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
    logger.info(
        f"Queueing analysis for {pr_info['owner']}/{pr_info['repo']}"
        f"#{pr_info['number']} ({pr_info['action']})"
    )

    background_tasks.add_task(
        analyze_pull_request,
        owner=pr_info["owner"],
        repo=pr_info["repo"],
        number=pr_info["number"],
        head_sha=pr_info["head_sha"],
        action=pr_info["action"],
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


class AnalyzePRRequest(BaseModel):
    """Request to manually analyze a GitHub PR."""

    owner: str = Field(..., description="Repository owner (user or org)")
    repo: str = Field(..., description="Repository name")
    number: int = Field(..., description="PR number")
    token: str | None = Field(None, description="GitHub token override (optional)")


@github_router.post("/analyze-pr")
async def trigger_pr_analysis(
    request: AnalyzePRRequest,
    background_tasks: BackgroundTasks,
):
    """Manually trigger DiffLens analysis on a GitHub PR."""
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


@github_router.get("/status")
async def github_status():
    """Check the status of GitHub integration."""
    settings = get_settings()

    status = {
        "configured": bool(settings.github_token),
        "webhook_secret_set": bool(settings.github_webhook_secret),
        "features": {
            "post_comment": settings.github_post_comment,
            "post_review": settings.github_post_review,
            "use_checks_api": settings.github_use_checks_api,
            "analyze_drafts": settings.github_analyze_drafts,
            "smart_review_on_prs": settings.github_enable_smart_review,
        },
        "public_url": settings.app_public_url,
    }

    # Verify token if configured
    if settings.github_token:
        try:
            client = GitHubClient()
            user = await client.verify_token()
            status["authenticated_as"] = user.get("login")
            status["token_scopes"] = "valid"
        except Exception as e:
            status["token_error"] = str(e)

    return status


@github_router.get("/prs")
def list_analyzed_prs(
    limit: int = 20,
    repo: str | None = None,
    db: Session = Depends(get_db),
):
    """List GitHub PRs that have been analyzed by DiffLens."""
    query = db.query(GitHubPR).join(AnalysisRun).order_by(GitHubPR.created_at.desc())

    if repo:
        # Filter by "owner/repo" format
        parts = repo.split("/")
        if len(parts) == 2:
            query = query.filter(
                GitHubPR.owner == parts[0],
                GitHubPR.repo == parts[1],
            )

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
            "created_at": pr.created_at.isoformat() if pr.created_at else None,
            "summary": pr.run.summary if pr.run else None,
        }
        for pr in prs
    ]
