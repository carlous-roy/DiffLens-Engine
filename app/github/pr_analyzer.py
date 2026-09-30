"""The GitHub pull request flow: status, diff, history, analysis, comments, persistence."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx
from fastapi.concurrency import run_in_threadpool

from app.analysis.diff_parser import parse_diff
from app.analysis.pipeline import AnalysisResult, run_analysis
from app.config import get_settings
from app.db import SessionLocal
from app.db.models import GitHubPR
from app.db.persist import persist_run
from app.github.client import SHA_RE, GitHubClient, validate_repo_name
from app.github.formatter import (
    SUMMARY_MARKER,
    findings_to_annotations,
    findings_to_review_comments,
    format_summary_comment,
    risk_level_to_conclusion,
    risk_level_to_status_state,
)
from app.github.history import collect_author_history
from app.ml.smart_review import smart_review

logger = logging.getLogger(__name__)


async def analyze_pull_request(
    owner: str,
    repo: str,
    number: int,
    head_sha: str,
    action: str = "opened",
    token: str | None = None,
    author: str | None = None,
    base_ref: str | None = None,
    created_at: datetime | None = None,
    client: GitHubClient | None = None,
    session_factory=None,
) -> dict:
    """Full PR analysis flow: status, diff, history, analysis, comments, persistence.

    `client` and `session_factory` are injection points for tests; the
    webhook and manual routes leave them unset.
    """
    settings = get_settings()
    result_info = {
        "owner": owner,
        "repo": repo,
        "pr_number": number,
        "head_sha": head_sha,
        "status": "pending",
    }
    try:
        validate_repo_name(owner, "owner")
        validate_repo_name(repo, "repo")
        if not SHA_RE.match(head_sha or ""):
            raise ValueError(f"Invalid head sha: {head_sha!r}")
        if int(number) < 1:
            raise ValueError(f"Invalid pull request number: {number!r}")
    except ValueError as exc:
        logger.error("Refusing PR analysis: %s", exc)
        result_info.update(status="error", error=str(exc))
        return result_info

    client = client or GitHubClient(token=token)
    session_factory = session_factory or SessionLocal

    try:
        await client.set_commit_status(
            owner,
            repo,
            head_sha,
            state="pending",
            description="DiffLens is analyzing your code...",
            target_url=f"{settings.app_public_url}/runs" if settings.app_public_url else None,
        )
        logger.info("Set pending status for %s/%s#%s @ %s", owner, repo, number, head_sha[:8])
    except Exception as e:
        logger.warning("Failed to set pending status: %s", e)

    try:
        diff_text = await client.get_pr_diff(owner, repo, number, max_bytes=settings.max_diff_bytes)
        if not diff_text or not diff_text.strip():
            logger.warning("Empty diff for %s/%s#%s", owner, repo, number)
            await _set_final_status(
                client, owner, repo, head_sha, "success", "No code changes to analyze."
            )
            result_info["status"] = "skipped"
            return result_info
    except ValueError as e:
        logger.warning("Skipping %s/%s#%s: %s", owner, repo, number, e)
        await _set_final_status(client, owner, repo, head_sha, "error", f"DiffLens skipped: {e}")
        result_info.update(status="skipped", error=str(e))
        return result_info
    except Exception as e:
        logger.error("Failed to fetch diff: %s", e)
        await _set_final_status(
            client, owner, repo, head_sha, "error", f"Failed to fetch diff: {e}"
        )
        result_info.update(status="error", error=str(e))
        return result_info

    history = None
    if base_ref and settings.github_history_max_files > 0:
        try:
            history = await collect_author_history(
                client,
                owner,
                repo,
                base_ref,
                parse_diff(diff_text),
                author,
                until=created_at or datetime.now(UTC),
                max_files=settings.github_history_max_files,
            )
        except Exception as e:
            logger.warning("History features unavailable for %s/%s#%s: %s", owner, repo, number, e)
    result_info["history_measured"] = history is not None

    try:
        analysis = await run_in_threadpool(run_analysis, diff_text, True, history)
        logger.info(
            "Analysis complete for %s/%s#%s: %d findings, risk=%s",
            owner,
            repo,
            number,
            analysis.total_findings,
            (analysis.risk_score or {}).get("level"),
        )
    except Exception as e:
        logger.error("Analysis failed: %s", e)
        await _set_final_status(client, owner, repo, head_sha, "error", f"Analysis failed: {e}")
        result_info.update(status="error", error=str(e))
        return result_info

    smart_review_result = None
    if settings.ml_enable_smart_review and settings.github_enable_smart_review:
        try:
            sr = await smart_review(diff_text, static_findings=analysis.to_dict())
            smart_review_result = sr.to_dict()
        except Exception as e:
            logger.warning("Smart review failed (non-fatal): %s", e)

    comment_id = None
    try:
        comment_id = await _post_results(
            client,
            owner,
            repo,
            number,
            head_sha,
            analysis,
            smart_review_result,
            settings,
            author=author,
            session_factory=session_factory,
        )
        result_info["status"] = "completed"
    except Exception as e:
        logger.error("Failed to post results to GitHub: %s", e)
        result_info["status"] = "completed_no_post"
        result_info["post_error"] = str(e)

    try:
        run_id = await run_in_threadpool(
            _persist,
            session_factory,
            analysis,
            {
                "owner": owner,
                "repo": repo,
                "pr_number": number,
                "head_sha": head_sha,
                "action": action,
                "comment_id": comment_id,
            },
        )
        result_info["run_id"] = run_id
    except Exception as e:
        logger.error("Failed to persist analysis: %s", e)
        result_info["persist_error"] = str(e)

    return result_info


async def _post_results(
    client: GitHubClient,
    owner: str,
    repo: str,
    number: int,
    head_sha: str,
    analysis: AnalysisResult,
    smart_review_result: dict | None,
    settings,
    author: str | None,
    session_factory,
) -> int | None:
    """Post the results to GitHub. Returns the id of the summary comment."""
    risk_level = "low"
    if analysis.risk_score and isinstance(analysis.risk_score, dict):
        risk_level = analysis.risk_score.get("level", "low")

    status_state = risk_level_to_status_state(risk_level)
    status_desc = f"{analysis.total_findings} findings · Risk: {risk_level.upper()}"
    run_url = f"{settings.app_public_url}/runs" if settings.app_public_url else None

    await client.set_commit_status(
        owner, repo, head_sha, state=status_state, description=status_desc, target_url=run_url
    )

    comment_id = None
    if settings.github_post_comment:
        comment_body = format_summary_comment(analysis, smart_review_result)
        comment_id = await _upsert_summary_comment(
            client, owner, repo, number, comment_body, session_factory
        )

    if settings.github_post_review and analysis.total_findings > 0:
        review_comments = findings_to_review_comments(analysis)
        if review_comments:
            review_body = (
                f"🔍 **DiffLens** found **{analysis.total_findings}** issues "
                f"(Risk: {risk_level.upper()})"
            )
            event = await _review_event(client, risk_level, author)
            try:
                await client.create_pr_review(
                    owner,
                    repo,
                    number,
                    head_sha,
                    body=review_body,
                    event=event,
                    comments=review_comments[:25],  # Limit inline comments
                )
            except Exception as e:
                logger.warning("Inline review comments skipped: %s", e)

    if settings.github_use_checks_api:
        try:
            check = await client.create_check_run(owner, repo, head_sha)
            check_id = check["id"]
            annotations = findings_to_annotations(analysis)
            conclusion = risk_level_to_conclusion(risk_level)
            summary_md = format_summary_comment(analysis, smart_review_result)
            await client.update_check_run(
                owner,
                repo,
                check_id,
                conclusion=conclusion,
                title=f"DiffLens: {analysis.total_findings} findings",
                summary=summary_md,
                annotations=annotations[:50],
            )
        except Exception as e:
            logger.warning("Check run API failed (token may lack checks:write): %s", e)

    return comment_id


async def _review_event(client: GitHubClient, risk_level: str, author: str | None) -> str:
    """REQUEST_CHANGES for high risk, unless the token's user authored the PR.

    GitHub rejects a user requesting changes on their own pull request, so
    in that case the review is posted as a comment.
    """
    if risk_level != "high":
        return "COMMENT"
    login = await client.authenticated_login()
    if author and login and author.lower() == login.lower():
        logger.info("PR author owns the token; posting the review as a comment.")
        return "COMMENT"
    return "REQUEST_CHANGES"


async def _upsert_summary_comment(
    client: GitHubClient,
    owner: str,
    repo: str,
    number: int,
    body: str,
    session_factory,
) -> int | None:
    """Update the summary comment from an earlier run of this PR, or post a new one.

    The previous comment id comes from the database; if it is unknown, the
    conversation is scanned for the hidden marker the formatter embeds.
    """
    previous = await run_in_threadpool(_previous_comment_id, session_factory, owner, repo, number)
    if previous is None:
        try:
            for comment in await client.list_issue_comments(owner, repo, number):
                if SUMMARY_MARKER in (comment.get("body") or ""):
                    previous = int(comment["id"])
                    break
        except Exception as e:
            logger.warning("Could not list PR comments: %s", e)

    if previous is not None:
        try:
            updated = await client.update_comment(owner, repo, previous, body)
            return int(updated.get("id", previous))
        except httpx.HTTPStatusError as e:
            logger.warning(
                "Could not update comment %s (%s); posting a new one.",
                previous,
                e.response.status_code,
            )

    created = await client.post_comment(owner, repo, number, body)
    return int(created["id"]) if created.get("id") is not None else None


def _previous_comment_id(session_factory, owner: str, repo: str, number: int) -> int | None:
    db = session_factory()
    try:
        row = (
            db.query(GitHubPR)
            .filter(
                GitHubPR.owner == owner,
                GitHubPR.repo == repo,
                GitHubPR.pr_number == number,
                GitHubPR.comment_id.isnot(None),
            )
            .order_by(GitHubPR.created_at.desc())
            .first()
        )
        return int(row.comment_id) if row else None
    finally:
        db.close()


async def _set_final_status(
    client: GitHubClient, owner: str, repo: str, sha: str, state: str, description: str
):
    """Helper to set final commit status, swallowing errors."""
    try:
        await client.set_commit_status(owner, repo, sha, state=state, description=description)
    except Exception as e:
        logger.warning("Failed to set final status: %s", e)


def _persist(session_factory, analysis: AnalysisResult, github: dict) -> str:
    db = session_factory()
    try:
        run = persist_run(db, analysis, source="github", github=github)
        return str(run.id)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
