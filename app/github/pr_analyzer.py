"""PR analysis service — orchestrates the full GitHub PR review flow."""
import logging
from typing import Optional
from datetime import datetime, timezone

from app.analysis.pipeline import run_analysis, AnalysisResult
from app.github.client import GitHubClient, PRInfo
from app.github.formatter import (
    format_summary_comment,
    findings_to_annotations,
    findings_to_review_comments,
    risk_level_to_conclusion,
    risk_level_to_status_state,
)
from app.db import SessionLocal
from app.db.models import AnalysisRun, AnalysisFinding, SeverityLevel, GitHubPR
from app.config import get_settings
from app.ml.smart_review import smart_review

logger = logging.getLogger(__name__)

async def analyze_pull_request(
    owner: str,
    repo: str,
    number: int,
    head_sha: str,
    action: str = "opened",
    token: Optional[str] = None,
) -> dict:
    """Full PR analysis flow."""
    settings = get_settings()
    client = GitHubClient(token=token)
    result_info = {
        "owner": owner,
        "repo": repo,
        "pr_number": number,
        "head_sha": head_sha,
        "status": "pending",
    }

    try:
        await client.set_commit_status(
            owner, repo, head_sha,
            state="pending",
            description="DiffLens is analyzing your code...",
            target_url=f"{settings.app_public_url}/runs" if settings.app_public_url else None,
        )
        logger.info(f"Set pending status for {owner}/{repo}#{number} @ {head_sha[:8]}")
    except Exception as e:
        logger.warning(f"Failed to set pending status: {e}")

    try:
        diff_text = await client.get_pr_diff(owner, repo, number)
        if not diff_text or not diff_text.strip():
            logger.warning(f"Empty diff for {owner}/{repo}#{number}")
            await _set_final_status(client, owner, repo, head_sha, "success",
                                     "No code changes to analyze.")
            result_info["status"] = "skipped"
            return result_info
    except Exception as e:
        logger.error(f"Failed to fetch diff: {e}")
        await _set_final_status(client, owner, repo, head_sha, "error",
                                 f"Failed to fetch diff: {e}")
        result_info["status"] = "error"
        result_info["error"] = str(e)
        return result_info

    try:
        analysis = run_analysis(diff_text, enable_ml=True)
        logger.info(
            f"Analysis complete: {analysis.total_findings} findings, "
            f"risk={analysis.risk_score}"
        )
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        await _set_final_status(client, owner, repo, head_sha, "error",
                                 f"Analysis failed: {e}")
        result_info["status"] = "error"
        result_info["error"] = str(e)
        return result_info

    smart_review_result = None
    if settings.ml_enable_smart_review and settings.github_enable_smart_review:
        try:
            sr = await smart_review(diff_text, static_findings=analysis.to_dict())
            smart_review_result = sr.to_dict()
        except Exception as e:
            logger.warning(f"Smart review failed (non-fatal): {e}")

    try:
        await _post_results(
            client, owner, repo, number, head_sha,
            analysis, smart_review_result, settings,
        )
        result_info["status"] = "completed"
    except Exception as e:
        logger.error(f"Failed to post results to GitHub: {e}")
        result_info["status"] = "completed_no_post"
        result_info["post_error"] = str(e)

    try:
        run_id = _persist_analysis(
            owner, repo, number, head_sha, action,
            diff_text, analysis, smart_review_result,
        )
        result_info["run_id"] = str(run_id)
    except Exception as e:
        logger.error(f"Failed to persist analysis: {e}")
        result_info["persist_error"] = str(e)

    return result_info

async def _post_results(
    client: GitHubClient,
    owner: str,
    repo: str,
    number: int,
    head_sha: str,
    analysis: AnalysisResult,
    smart_review_result: Optional[dict],
    settings,
):
    """Post analysis results back to GitHub via multiple channels."""

    risk_level = "low"
    if analysis.risk_score and isinstance(analysis.risk_score, dict):
        risk_level = analysis.risk_score.get("level", "low")

    status_state = risk_level_to_status_state(risk_level)
    status_desc = (
        f"{analysis.total_findings} findings · "
        f"Risk: {risk_level.upper()}"
    )
    run_url = f"{settings.app_public_url}/runs" if settings.app_public_url else None

    await client.set_commit_status(
        owner, repo, head_sha,
        state=status_state,
        description=status_desc,
        target_url=run_url,
    )

    if settings.github_post_comment:
        comment_body = format_summary_comment(analysis, smart_review_result)
        await client.post_comment(owner, repo, number, comment_body)

    if settings.github_post_review and analysis.total_findings > 0:
        review_comments = findings_to_review_comments(analysis)
        if review_comments:
            review_body = (
                f"🔍 **DiffLens** found **{analysis.total_findings}** issues "
                f"(Risk: {risk_level.upper()})"
            )
            event = "REQUEST_CHANGES" if risk_level in ("high", "critical") else "COMMENT"
            try:
                await client.create_pr_review(
                    owner, repo, number, head_sha,
                    body=review_body,
                    event=event,
                    comments=review_comments[:25],  # Limit inline comments
                )
            except Exception as e:
                # Fall back to summary-only if inline comments fail
                # (can happen if line positions are stale)
                logger.warning(f"Inline review comments skipped: {e}")

    if settings.github_use_checks_api:
        try:
            check = await client.create_check_run(owner, repo, head_sha)
            check_id = check["id"]

            annotations = findings_to_annotations(analysis)
            conclusion = risk_level_to_conclusion(risk_level)
            summary_md = format_summary_comment(analysis, smart_review_result)

            await client.update_check_run(
                owner, repo, check_id,
                conclusion=conclusion,
                title=f"DiffLens: {analysis.total_findings} findings",
                summary=summary_md,
                annotations=annotations[:50],
            )
        except Exception as e:
            logger.warning(f"Check run API failed (token may lack checks:write): {e}")

async def _set_final_status(
    client: GitHubClient,
    owner: str,
    repo: str,
    sha: str,
    state: str,
    description: str,
):
    """Helper to set final commit status, swallowing errors."""
    try:
        await client.set_commit_status(owner, repo, sha, state=state, description=description)
    except Exception as e:
        logger.warning(f"Failed to set final status: {e}")

def _persist_analysis(
    owner: str,
    repo: str,
    number: int,
    head_sha: str,
    action: str,
    diff_text: str,
    analysis: AnalysisResult,
    smart_review_result: Optional[dict],
) -> str:
    """Persist the analysis run and GitHub PR metadata to the database."""
    db = SessionLocal()
    try:
        # Create analysis run
        run = AnalysisRun(
            source="github",
            summary=analysis.summary,
        )
        db.add(run)
        db.flush()

        # Create GitHub PR record
        pr_record = GitHubPR(
            run_id=run.id,
            owner=owner,
            repo=repo,
            pr_number=number,
            head_sha=head_sha,
            action=action,
            pr_url=f"https://github.com/{owner}/{repo}/pull/{number}",
        )
        db.add(pr_record)

        # Persist findings
        all_findings = []
        for f in analysis.complexity_findings:
            all_findings.append(AnalysisFinding(
                run_id=run.id, analyzer="complexity",
                file_path=f["file_path"], line_number=f.get("line_number"),
                severity=SeverityLevel(f["severity"].lower()),
                message=f["message"], suggestion=f.get("suggestion"),
                metadata_={"function_name": f.get("function_name"), "complexity": f.get("complexity")},
            ))
        for f in analysis.naming_findings:
            all_findings.append(AnalysisFinding(
                run_id=run.id, analyzer="naming",
                file_path=f["file_path"], line_number=f.get("line_number"),
                severity=SeverityLevel(f["severity"].lower()),
                message=f["message"], suggestion=f.get("suggestion"),
                metadata_={"name": f.get("name"), "kind": f.get("kind")},
            ))
        for f in analysis.bug_risk_findings:
            all_findings.append(AnalysisFinding(
                run_id=run.id, analyzer="bug_risk",
                file_path=f["file_path"], line_number=f.get("line_number"),
                severity=SeverityLevel(f["severity"].lower()),
                message=f["message"], suggestion=f.get("suggestion"),
                metadata_={"rule_id": f.get("rule_id"), "matched_text": f.get("matched_text")},
            ))

        db.add_all(all_findings)
        db.commit()
        return str(run.id)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
