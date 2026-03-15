"""Smart Code Review — LLM-powered review comment generation."""
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

from app.ml.llm_provider import get_llm_provider, LLMResponse

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert code reviewer. You analyze code diffs and provide clear,
actionable review comments. For each issue you find:

1. State the problem concisely
2. Explain WHY it's a problem (impact on reliability, security, performance, or readability)
3. Suggest a specific fix with a brief code example when helpful

Keep comments professional, constructive, and prioritized by severity.
Respond ONLY with valid JSON in this exact format:
{
  "comments": [
    {
      "file": "path/to/file.py",
      "line": 10,
      "severity": "error|warning|info",
      "category": "security|correctness|performance|maintainability|style",
      "comment": "Clear description of the issue",
      "suggestion": "Specific fix suggestion with code if applicable"
    }
  ],
  "overall_summary": "1-2 sentence summary of the change quality"
}"""

@dataclass
class ReviewComment:
    """A single LLM-generated review comment."""
    file: str
    line: Optional[int]
    severity: str
    category: str
    comment: str
    suggestion: Optional[str] = None

@dataclass
class SmartReviewResult:
    """Complete result from the smart review."""
    comments: list[ReviewComment] = field(default_factory=list)
    overall_summary: str = ""
    model_used: str = ""
    tokens_used: Optional[int] = None
    error: Optional[str] = None
    llm_available: bool = True

    def to_dict(self) -> dict:
        return {
            "comments": [asdict(c) for c in self.comments],
            "overall_summary": self.overall_summary,
            "model_used": self.model_used,
            "tokens_used": self.tokens_used,
            "error": self.error,
            "llm_available": self.llm_available,
        }

def _build_review_prompt(diff_text: str, static_findings: Optional[dict] = None) -> str:
    """Build the prompt that combines diff + static analysis context."""
    # Truncate very large diffs to stay within context window
    max_diff_chars = 6000
    truncated = diff_text[:max_diff_chars]
    if len(diff_text) > max_diff_chars:
        truncated += "\n... [diff truncated for length]"

    prompt = f"Review this code diff:\n\n```diff\n{truncated}\n```\n"

    if static_findings:
        findings_summary = []
        for key in ("complexity_findings", "naming_findings", "bug_risk_findings"):
            for f in static_findings.get(key, []):
                findings_summary.append(
                    f"- [{f.get('severity', 'info').upper()}] {f.get('file_path', '?')}:"
                    f"{f.get('line_number', '?')} — {f.get('message', '')}"
                )
        if findings_summary:
            prompt += "\n\nStatic analysis already found these issues:\n"
            prompt += "\n".join(findings_summary[:15])  # Cap at 15 findings
            prompt += "\n\nProvide additional insights beyond what static analysis found."
            prompt += " Focus on logic errors, design issues, and subtle bugs."

    return prompt

def _parse_llm_response(raw: str) -> tuple[list[ReviewComment], str]:
    """Parse the LLM JSON response into structured comments."""
    comments = []
    summary = ""

    # Try to extract JSON from the response (LLMs sometimes add markdown fences)
    text = raw.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0]

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to find any JSON object in the response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start:end])
            except json.JSONDecodeError:
                logger.warning("Could not parse LLM response as JSON")
                return [ReviewComment(
                    file="general",
                    line=None,
                    severity="info",
                    category="maintainability",
                    comment=raw[:500],
                )], "LLM response could not be parsed as structured JSON."
        else:
            return [ReviewComment(
                file="general",
                line=None,
                severity="info",
                category="maintainability",
                comment=raw[:500],
            )], "LLM response was not structured JSON."

    summary = data.get("overall_summary", "")

    for c in data.get("comments", []):
        comments.append(ReviewComment(
            file=c.get("file", "unknown"),
            line=c.get("line"),
            severity=c.get("severity", "info"),
            category=c.get("category", "maintainability"),
            comment=c.get("comment", ""),
            suggestion=c.get("suggestion"),
        ))

    return comments, summary

async def smart_review(diff_text: str, static_findings: Optional[dict] = None) -> SmartReviewResult:
    """Run LLM-powered smart review on a diff."""
    provider = get_llm_provider()

    # Check if LLM is available
    available = await provider.is_available()
    if not available:
        return SmartReviewResult(
            llm_available=False,
            error="LLM service not available. Start Ollama to enable smart reviews.",
        )

    prompt = _build_review_prompt(diff_text, static_findings)
    response: LLMResponse = await provider.generate(prompt, system_prompt=SYSTEM_PROMPT)

    if not response.ok:
        return SmartReviewResult(
            model_used=response.model,
            error=response.error,
            llm_available=True,
        )

    comments, summary = _parse_llm_response(response.content)

    return SmartReviewResult(
        comments=comments,
        overall_summary=summary,
        model_used=response.model,
        tokens_used=response.tokens_used,
        llm_available=True,
    )
