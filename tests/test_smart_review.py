"""Tests for the smart review module."""

import pytest

from app.ml.smart_review import _build_review_prompt, _parse_llm_response


class TestParseResponse:
    def test_valid_json(self):
        raw = """{
            "comments": [
                {
                    "file": "test.py",
                    "line": 10,
                    "severity": "error",
                    "category": "security",
                    "comment": "eval() is dangerous",
                    "suggestion": "Use ast.literal_eval()"
                }
            ],
            "overall_summary": "Code has security issues."
        }"""
        comments, summary = _parse_llm_response(raw)
        assert len(comments) == 1
        assert comments[0].file == "test.py"
        assert comments[0].severity == "error"
        assert comments[0].category == "security"
        assert summary == "Code has security issues."

    def test_json_in_markdown_fences(self):
        raw = """```json
        {
            "comments": [{"file": "a.py", "line": 1, "severity": "info",
                          "category": "style", "comment": "test"}],
            "overall_summary": "OK"
        }
        ```"""
        comments, summary = _parse_llm_response(raw)
        assert len(comments) == 1
        assert summary == "OK"

    def test_invalid_json_fallback(self):
        raw = "This is not JSON at all, just a text response about code quality."
        comments, summary = _parse_llm_response(raw)
        assert len(comments) == 1  # Fallback comment
        assert comments[0].file == "general"

    def test_empty_comments(self):
        raw = '{"comments": [], "overall_summary": "Clean code."}'
        comments, summary = _parse_llm_response(raw)
        assert len(comments) == 0
        assert summary == "Clean code."

    def test_partial_comment_fields(self):
        raw = """{
            "comments": [{"comment": "Missing fields test"}],
            "overall_summary": ""
        }"""
        comments, summary = _parse_llm_response(raw)
        assert len(comments) == 1
        assert comments[0].file == "unknown"
        assert comments[0].severity == "info"


class TestBuildPrompt:
    def test_basic_prompt(self):
        prompt = _build_review_prompt("diff --git a/test.py b/test.py\n+x = 1")
        assert "diff" in prompt
        assert "test.py" in prompt

    def test_with_static_findings(self):
        findings = {
            "complexity_findings": [
                {
                    "severity": "warning",
                    "file_path": "a.py",
                    "line_number": 10,
                    "message": "Function too complex",
                },
            ],
            "naming_findings": [],
            "bug_risk_findings": [],
        }
        prompt = _build_review_prompt("diff content", static_findings=findings)
        assert "Static analysis" in prompt
        assert "Function too complex" in prompt

    def test_truncation(self):
        long_diff = "+" + "x" * 10000
        prompt = _build_review_prompt(long_diff)
        assert "truncated" in prompt
        assert len(prompt) < 10000


class TestStubProviderEndToEnd:
    """LLM_PROVIDER=stub exercises the whole review path without a model."""

    @pytest.fixture(autouse=True)
    def _stub_provider(self, monkeypatch):
        from app.config import get_settings
        from app.ml import llm_provider

        monkeypatch.setenv("LLM_PROVIDER", "stub")
        monkeypatch.setenv("API_KEY", "k")
        get_settings.cache_clear()
        llm_provider._provider = None
        yield
        get_settings.cache_clear()
        llm_provider._provider = None

    async def test_smart_review_returns_parsed_comments(self):
        from app.ml.smart_review import smart_review

        result = await smart_review("diff --git a/x.py b/x.py\n+eval(x)\n")
        assert result.llm_available is True
        assert result.error is None
        assert result.model_used == "stub"
        assert result.comments[0].category == "maintainability"
        assert "Stub provider" in result.overall_summary

    def test_smart_review_route_requires_key(self, client):
        assert client.post("/api/v1/smart-review", json={"diff": "+x"}).status_code == 401
        resp = client.post("/api/v1/smart-review", json={"diff": "+x"}, headers={"X-API-Key": "k"})
        assert resp.status_code == 200
        assert resp.json()["model_used"] == "stub"

    def test_analyze_with_llm_pass_requires_key(self, client):
        from tests.conftest import MINIMAL_PYTHON_DIFF

        body = {"diff": MINIMAL_PYTHON_DIFF, "enable_smart_review": True}
        assert client.post("/api/v1/analyze", json=body).status_code == 401
        resp = client.post("/api/v1/analyze", json=body, headers={"X-API-Key": "k"})
        assert resp.status_code == 200
        assert resp.json()["smart_review"]["model_used"] == "stub"
        # Without the LLM pass no key is needed.
        assert client.post("/api/v1/analyze", json={"diff": MINIMAL_PYTHON_DIFF}).status_code == 200


def test_smart_review_route_is_503_without_a_configured_key(client):
    assert client.post("/api/v1/smart-review", json={"diff": "+x"}).status_code == 503


def test_llm_output_is_flattened_before_posting():
    from app.github.formatter import plain_text

    assert plain_text("<script>alert(1)</script> fine <b>bold</b>", 100) == "alert(1) fine bold"
    assert plain_text("a   b\n\nc", 100) == "a b c"
    assert plain_text("x" * 50, 10).endswith("…")
    assert len(plain_text("x" * 50, 10)) == 10
