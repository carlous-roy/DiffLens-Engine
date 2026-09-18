"""GitHub REST API client for DiffLens."""

import logging
from dataclasses import dataclass

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


@dataclass
class PRInfo:
    """Extracted pull request metadata."""

    owner: str
    repo: str
    number: int
    head_sha: str
    title: str
    author: str
    base_ref: str
    head_ref: str
    html_url: str
    additions: int = 0
    deletions: int = 0
    changed_files: int = 0


class GitHubClient:
    """Async client for GitHub REST API v3."""

    def __init__(self, token: str | None = None):
        settings = get_settings()
        self.token = token or settings.github_token
        if not self.token:
            raise ValueError("GitHub token is required. Set GITHUB_TOKEN environment variable.")
        self._headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=GITHUB_API_BASE,
            headers=self._headers,
            timeout=30.0,
        )

    async def get_pr(self, owner: str, repo: str, number: int) -> PRInfo:
        """Fetch pull request metadata."""
        async with self._client() as client:
            resp = await client.get(f"/repos/{owner}/{repo}/pulls/{number}")
            resp.raise_for_status()
            data = resp.json()

        return PRInfo(
            owner=owner,
            repo=repo,
            number=number,
            head_sha=data["head"]["sha"],
            title=data["title"],
            author=data["user"]["login"],
            base_ref=data["base"]["ref"],
            head_ref=data["head"]["ref"],
            html_url=data["html_url"],
            additions=data.get("additions", 0),
            deletions=data.get("deletions", 0),
            changed_files=data.get("changed_files", 0),
        )

    async def get_pr_diff(self, owner: str, repo: str, number: int) -> str:
        """Fetch the unified diff for a pull request."""
        headers = {**self._headers, "Accept": "application/vnd.github.v3.diff"}
        async with httpx.AsyncClient(
            base_url=GITHUB_API_BASE, headers=headers, timeout=60.0
        ) as client:
            resp = await client.get(f"/repos/{owner}/{repo}/pulls/{number}")
            resp.raise_for_status()
            return resp.text

    async def get_pr_files(self, owner: str, repo: str, number: int) -> list[dict]:
        """Fetch the list of changed files in a PR."""
        async with self._client() as client:
            resp = await client.get(
                f"/repos/{owner}/{repo}/pulls/{number}/files",
                params={"per_page": 100},
            )
            resp.raise_for_status()
            return resp.json()

    async def set_commit_status(
        self,
        owner: str,
        repo: str,
        sha: str,
        state: str,
        description: str,
        target_url: str | None = None,
        context: str = "DiffLens",
    ) -> dict:
        """Set a commit status (pending, success, failure, error)."""
        payload = {
            "state": state,
            "description": description[:140],  # GitHub limit
            "context": context,
        }
        if target_url:
            payload["target_url"] = target_url

        async with self._client() as client:
            resp = await client.post(
                f"/repos/{owner}/{repo}/statuses/{sha}",
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    async def create_check_run(
        self,
        owner: str,
        repo: str,
        head_sha: str,
        name: str = "DiffLens Analysis",
        status: str = "in_progress",
    ) -> dict:
        """Create a GitHub Check Run.

        Requires a GitHub App or a fine-grained token with checks:write.
        """
        payload = {
            "name": name,
            "head_sha": head_sha,
            "status": status,
        }
        async with self._client() as client:
            resp = await client.post(
                f"/repos/{owner}/{repo}/check-runs",
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    async def update_check_run(
        self,
        owner: str,
        repo: str,
        check_run_id: int,
        conclusion: str,
        title: str,
        summary: str,
        annotations: list[dict] | None = None,
    ) -> dict:
        """Update a check run with conclusion and annotations."""
        output = {"title": title, "summary": summary}
        if annotations:
            # GitHub limits to 50 annotations per request
            output["annotations"] = annotations[:50]

        payload = {
            "status": "completed",
            "conclusion": conclusion,
            "output": output,
        }
        async with self._client() as client:
            resp = await client.patch(
                f"/repos/{owner}/{repo}/check-runs/{check_run_id}",
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    async def create_pr_review(
        self,
        owner: str,
        repo: str,
        number: int,
        commit_id: str,
        body: str,
        event: str = "COMMENT",
        comments: list[dict] | None = None,
    ) -> dict:
        """Create a pull request review with optional inline comments."""
        payload = {
            "commit_id": commit_id,
            "body": body,
            "event": event,
        }
        if comments:
            payload["comments"] = comments

        async with self._client() as client:
            resp = await client.post(
                f"/repos/{owner}/{repo}/pulls/{number}/reviews",
                json=payload,
            )
            # GitHub returns 422 when inline comment positions are outside
            # the diff range. Gracefully degrade to a review without inline
            # comments — the summary comment still covers all findings.
            if resp.status_code == 422 and comments:
                logger.warning(
                    "Inline comments outside diff range (422), "
                    "posting review without inline comments."
                )
                payload.pop("comments", None)
                resp = await client.post(
                    f"/repos/{owner}/{repo}/pulls/{number}/reviews",
                    json=payload,
                )
            resp.raise_for_status()
            return resp.json()

    async def post_comment(
        self,
        owner: str,
        repo: str,
        number: int,
        body: str,
    ) -> dict:
        """Post a general comment on a PR (issue comment)."""
        async with self._client() as client:
            resp = await client.post(
                f"/repos/{owner}/{repo}/issues/{number}/comments",
                json={"body": body},
            )
            resp.raise_for_status()
            return resp.json()

    async def verify_token(self) -> dict:
        """Verify the token is valid and return the authenticated user."""
        async with self._client() as client:
            resp = await client.get("/user")
            resp.raise_for_status()
            return resp.json()
