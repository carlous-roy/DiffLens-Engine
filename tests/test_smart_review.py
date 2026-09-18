"""Tests for the smart review module."""

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
