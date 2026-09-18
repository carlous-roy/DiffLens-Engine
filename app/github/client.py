"""GitHub REST API client for DiffLens."""

import logging
import re
from dataclasses import dataclass

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"

# GitHub user, organisation and repository names.
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


def validate_repo_name(value: str, what: str) -> str:
    """Reject anything that could not be a GitHub owner or repository name."""
    if not isinstance(value, str) or not NAME_RE.match(value):
        raise ValueError(f"Invalid {what}: {value!r}")
    return value


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
    """Async client for GitHub REST API v3.

    `transport` lets tests supply an `httpx.MockTransport`; nothing else in
    the client depends on the network being real.
    """

    def __init__(self, token: str | None = None, transport: httpx.AsyncBaseTransport | None = None):
        settings = get_settings()
        self.token = token or settings.github_token
        if not self.token:
            raise ValueError("GitHub token is required. Set GITHUB_TOKEN environment variable.")
        self._headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self._transport = transport
        self._login: str | None = None

    def _client(self, timeout: float = 30.0, **headers: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=GITHUB_API_BASE,
            headers={**self._headers, **headers},
            timeout=timeout,
            transport=self._transport,
        )

    @staticmethod
    def _repo_path(owner: str, repo: str) -> str:
        return f"/repos/{validate_repo_name(owner, 'owner')}/{validate_repo_name(repo, 'repo')}"

    async def get_pr(self, owner: str, repo: str, number: int) -> PRInfo:
        """Fetch pull request metadata."""
        async with self._client() as client:
            resp = await client.get(f"{self._repo_path(owner, repo)}/pulls/{int(number)}")
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

    async def get_pr_diff(
        self, owner: str, repo: str, number: int, max_bytes: int | None = None
    ) -> str:
        """Fetch the unified diff for a pull request.

        Raises `ValueError` when the diff is larger than `max_bytes`.
        """
        async with self._client(timeout=60.0, Accept="application/vnd.github.v3.diff") as client:
            resp = await client.get(f"{self._repo_path(owner, repo)}/pulls/{int(number)}")
            resp.raise_for_status()
            if max_bytes is not None and len(resp.content) > max_bytes:
                raise ValueError(
                    f"Diff is {len(resp.content)} bytes, above the {max_bytes} byte limit."
                )
            return resp.text

    async def get_pr_files(self, owner: str, repo: str, number: int) -> list[dict]:
        """Fetch the list of changed files in a PR."""
        async with self._client() as client:
            resp = await client.get(
                f"{self._repo_path(owner, repo)}/pulls/{int(number)}/files",
                params={"per_page": 100},
            )
            resp.raise_for_status()
            return resp.json()

    async def list_commits(
        self,
        owner: str,
        repo: str,
        sha: str | None = None,
        path: str | None = None,
        author: str | None = None,
        until: str | None = None,
        per_page: int = 100,
        max_pages: int = 1,
    ) -> list[dict]:
        """List commits, following `Link: rel=next` for up to `max_pages` pages."""
        params: dict[str, str | int] = {"per_page": per_page}
        if sha:
            params["sha"] = sha
        if path:
            params["path"] = path
        if author:
            params["author"] = author
        if until:
            params["until"] = until
        commits: list[dict] = []
        url = f"{self._repo_path(owner, repo)}/commits"
        async with self._client() as client:
            for _ in range(max_pages):
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                commits.extend(resp.json())
                next_url = resp.links.get("next", {}).get("url")
                if not next_url:
                    break
                url, params = next_url, {}
        return commits

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
            resp = await client.post(f"{self._repo_path(owner, repo)}/statuses/{sha}", json=payload)
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
        payload = {"name": name, "head_sha": head_sha, "status": status}
        async with self._client() as client:
            resp = await client.post(f"{self._repo_path(owner, repo)}/check-runs", json=payload)
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

        payload = {"status": "completed", "conclusion": conclusion, "output": output}
        async with self._client() as client:
            resp = await client.patch(
                f"{self._repo_path(owner, repo)}/check-runs/{int(check_run_id)}", json=payload
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
        payload = {"commit_id": commit_id, "body": body, "event": event}
        if comments:
            payload["comments"] = comments

        async with self._client() as client:
            url = f"{self._repo_path(owner, repo)}/pulls/{int(number)}/reviews"
            resp = await client.post(url, json=payload)
            # GitHub returns 422 when inline comment positions are outside
            # the diff range. Degrade to a review without inline comments;
            # the summary comment still covers all findings.
            if resp.status_code == 422 and comments:
                logger.warning(
                    "Inline comments rejected by GitHub (422): %s; posting the review "
                    "without inline comments.",
                    resp.text[:300],
                )
                payload.pop("comments", None)
                resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()

    async def post_comment(self, owner: str, repo: str, number: int, body: str) -> dict:
        """Post a general comment on a PR (issue comment)."""
        async with self._client() as client:
            resp = await client.post(
                f"{self._repo_path(owner, repo)}/issues/{int(number)}/comments", json={"body": body}
            )
            resp.raise_for_status()
            return resp.json()

    async def list_issue_comments(self, owner: str, repo: str, number: int) -> list[dict]:
        """The first 100 comments on a PR conversation, oldest first."""
        async with self._client() as client:
            resp = await client.get(
                f"{self._repo_path(owner, repo)}/issues/{int(number)}/comments",
                params={"per_page": 100},
            )
            resp.raise_for_status()
            return resp.json()

    async def update_comment(self, owner: str, repo: str, comment_id: int, body: str) -> dict:
        """Edit an existing issue comment."""
        async with self._client() as client:
            resp = await client.patch(
                f"{self._repo_path(owner, repo)}/issues/comments/{int(comment_id)}",
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

    async def authenticated_login(self) -> str | None:
        """The login of the token's user, fetched once per client."""
        if self._login is None:
            try:
                self._login = (await self.verify_token()).get("login")
            except Exception as exc:
                logger.warning("Could not determine the token's login: %s", exc)
                return None
        return self._login
