"""An in-process stand-in for api.github.com, used through httpx.MockTransport.

It answers the endpoints the PR flow uses and records every request, so the
tests can assert on the exact sequence of calls without any network. Like
GitHub, it rejects a review whose inline comments point outside the diff.
"""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qs

import httpx

from app.analysis.diff_parser import parse_diff


class FakeGitHub:
    def __init__(
        self,
        diff: str,
        author: str = "alice",
        login: str = "difflens-bot",
        existing_comments: list[dict] | None = None,
        commits: dict[str, list[dict]] | None = None,
        author_commits: list[dict] | None = None,
        deleted_comment_ids: set[int] | None = None,
    ):
        self.diff = diff
        self.author = author
        self.login = login
        self.comments: dict[int, dict] = {c["id"]: c for c in (existing_comments or [])}
        self.commits = commits or {}
        self.author_commits = author_commits or []
        self.deleted_comment_ids = deleted_comment_ids or set()
        self.requests: list[httpx.Request] = []
        self.statuses: list[dict] = []
        self.reviews: list[dict] = []
        self._next_comment_id = 100
        self._diff_lines = self._lines_in_diff(diff)

    # ------------------------------------------------------------ helpers --

    @staticmethod
    def _lines_in_diff(diff: str) -> dict[str, set[int]]:
        lines: dict[str, set[int]] = {}
        for fdiff in parse_diff(diff):
            view = fdiff.post_image()
            lines[fdiff.path] = set(view.line_numbers)
        return lines

    def calls(
        self, method: str | None = None, path_pattern: str | None = None
    ) -> list[httpx.Request]:
        out = []
        for r in self.requests:
            if method and r.method != method:
                continue
            if path_pattern and not re.search(path_pattern, r.url.path):
                continue
            out.append(r)
        return out

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    # ------------------------------------------------------------ handler --

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        method = request.method
        query = parse_qs(request.url.query.decode())

        if path == "/user":
            return httpx.Response(200, json={"login": self.login, "id": 1})

        m = re.fullmatch(r"/repos/([^/]+)/([^/]+)/pulls/(\d+)", path)
        if m and method == "GET":
            if "diff" in request.headers.get("Accept", ""):
                return httpx.Response(200, text=self.diff)
            return httpx.Response(
                200,
                json={
                    "head": {"sha": "f" * 40, "ref": "feature"},
                    "base": {"ref": "main"},
                    "title": "Test PR",
                    "user": {"login": self.author},
                    "html_url": f"https://github.com/{m.group(1)}/{m.group(2)}/pull/{m.group(3)}",
                    "additions": 10,
                    "deletions": 2,
                    "changed_files": 1,
                },
            )

        if re.fullmatch(r"/repos/[^/]+/[^/]+/statuses/[0-9a-f]+", path) and method == "POST":
            self.statuses.append(json.loads(request.content))
            return httpx.Response(201, json={"id": len(self.statuses)})

        if re.fullmatch(r"/repos/[^/]+/[^/]+/commits", path) and method == "GET":
            if "author" in query:
                return httpx.Response(200, json=self.author_commits)
            return httpx.Response(200, json=self.commits.get(query.get("path", [""])[0], []))

        m = re.fullmatch(r"/repos/[^/]+/[^/]+/issues/(\d+)/comments", path)
        if m and method == "GET":
            return httpx.Response(200, json=list(self.comments.values()))
        if m and method == "POST":
            comment_id = self._next_comment_id
            self._next_comment_id += 1
            body = json.loads(request.content)["body"]
            self.comments[comment_id] = {
                "id": comment_id,
                "body": body,
                "user": {"login": self.login},
            }
            return httpx.Response(201, json={"id": comment_id})

        m = re.fullmatch(r"/repos/[^/]+/[^/]+/issues/comments/(\d+)", path)
        if m and method == "PATCH":
            comment_id = int(m.group(1))
            if comment_id in self.deleted_comment_ids or comment_id not in self.comments:
                return httpx.Response(404, json={"message": "Not Found"})
            self.comments[comment_id]["body"] = json.loads(request.content)["body"]
            return httpx.Response(200, json={"id": comment_id})

        m = re.fullmatch(r"/repos/[^/]+/[^/]+/pulls/(\d+)/reviews", path)
        if m and method == "POST":
            payload = json.loads(request.content)
            for comment in payload.get("comments", []):
                if comment.get("line") not in self._diff_lines.get(comment.get("path"), set()):
                    return httpx.Response(
                        422,
                        json={
                            "message": "Unprocessable Entity",
                            "errors": [f"line {comment.get('line')} is outside the diff"],
                        },
                    )
            self.reviews.append(payload)
            return httpx.Response(200, json={"id": len(self.reviews)})

        return httpx.Response(404, json={"message": f"unhandled {method} {path}"})
