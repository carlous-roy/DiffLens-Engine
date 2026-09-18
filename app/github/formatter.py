"""GitHub output formatter — converts DiffLens results into GitHub-friendly formats."""

from app.analysis.pipeline import AnalysisResult

SEVERITY_EMOJI = {
    "critical": "🔴",
    "error": "🟠",
    "warning": "🟡",
    "info": "🔵",
}

SEVERITY_TO_ANNOTATION_LEVEL = {
    "critical": "failure",
    "error": "failure",
    "warning": "warning",
    "info": "notice",
}


def format_summary_comment(
    analysis: AnalysisResult,
    smart_review: dict | None = None,
) -> str:
    """Format the full analysis result as a GitHub PR comment in Markdown."""
    risk_info = analysis.risk_score or {}
    risk_level = risk_info.get("level", "unknown")
    risk_score_val = risk_info.get("score", 0)
    risk_emoji = _risk_emoji(risk_level)

    lines = [
        "## 🔍 DiffLens Code Review",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| **Files analyzed** | {analysis.summary.get('files_analyzed', 0)} |",
        f"| **Total findings** | {analysis.total_findings} |",
        f"| **Risk level** | {risk_emoji} {risk_level.upper()} ({risk_score_val:.0%}) |",
    ]
    seen_before = analysis.summary.get("findings_seen_before")
    if seen_before:
        lines.append(f"| **Seen before** | {seen_before} of {analysis.total_findings} findings |")
    lines.append("")

    # Severity breakdown
    by_severity = analysis.summary.get("by_severity", {})
    if any(v > 0 for v in by_severity.values()):
        lines.append("### Findings by Severity")
        lines.append("")
        for sev in ("critical", "error", "warning", "info"):
            count = by_severity.get(sev, 0)
            if count > 0:
                emoji = SEVERITY_EMOJI.get(sev, "")
                lines.append(f"- {emoji} **{sev.capitalize()}**: {count}")
        lines.append("")

    # Analyzer breakdown
    by_analyzer = analysis.summary.get("by_analyzer", {})
    if any(v > 0 for v in by_analyzer.values()):
        lines.append("### Findings by Category")
        lines.append("")
        analyzer_labels = {
            "complexity": "🧩 Complexity",
            "naming": "📛 Naming",
            "bug_risk": "🐛 Bug Risk",
        }
        for analyzer, count in by_analyzer.items():
            if count > 0:
                label = analyzer_labels.get(analyzer, analyzer)
                lines.append(f"- {label}: {count}")
        lines.append("")

    # Risk contributing factors
    if risk_info.get("contributing_factors"):
        lines.append("### Risk Factors")
        lines.append("")
        for factor in risk_info["contributing_factors"][:5]:
            lines.append(f"- {factor}")
        lines.append("")

    # Top findings (limit to avoid huge comments)
    all_findings = _collect_top_findings(analysis, limit=10)
    if all_findings:
        lines.append("### Top Findings")
        lines.append("")
        lines.append("| Severity | File | Issue | Seen before |")
        lines.append("|----------|------|-------|-------------|")
        for f in all_findings:
            sev = f.get("severity", "info")
            emoji = SEVERITY_EMOJI.get(sev, "")
            file_path = f.get("file_path", "")
            line = f.get("line_number")
            loc = f"`{file_path}:{line}`" if line else f"`{file_path}`"
            msg = f.get("message", "")[:100]
            lines.append(f"| {emoji} {sev} | {loc} | {msg} | {seen_before_label(f)} |")
        lines.append("")

    # Smart review summary
    if smart_review and not smart_review.get("error"):
        lines.append("### 🤖 AI Review")
        lines.append("")
        comments = smart_review.get("comments", [])
        if comments:
            for c in comments[:5]:
                lines.append(
                    f"- **{c.get('file', '')}:{c.get('line', '')}** — {c.get('comment', '')}"
                )
            lines.append("")
        summary_text = smart_review.get("overall_summary", "")
        if summary_text:
            lines.append(f"> {summary_text}")
            lines.append("")

    # Categorization
    cat = analysis.categorization
    if cat and isinstance(cat, dict) and not cat.get("error"):
        category_counts = cat.get("summary", {})
        ranked = [(name, n) for name, n in category_counts.items() if n]
        ranked.sort(key=lambda item: item[1], reverse=True)
        if ranked:
            lines.append("### 📂 Categories")
            lines.append("")
            for label, count in ranked[:5]:
                lines.append(f"- **{label}**: {count} findings")
            lines.append("")

    lines.append("---")
    lines.append(
        "*Analyzed by [DiffLens](https://github.com/carlous-roy/DiffLens-Engine) "
        "· static analysis and change-risk scoring*"
    )

    return "\n".join(lines)


def findings_to_annotations(analysis: AnalysisResult) -> list[dict]:
    """Convert findings into GitHub Check Run annotations."""
    severity_order = {"critical": 0, "error": 1, "warning": 2, "info": 3}
    ranked: list[tuple[int, dict]] = []

    for f in _collect_all_findings(analysis):
        severity = f.get("severity", "info")
        line = f.get("line_number")
        if not line:
            continue  # Annotations require a line number

        ranked.append(
            (
                severity_order.get(severity, 4),
                {
                    "path": f.get("file_path", ""),
                    "start_line": line,
                    "end_line": line,
                    "annotation_level": SEVERITY_TO_ANNOTATION_LEVEL.get(severity, "notice"),
                    "title": f"[{f.get('analyzer', 'difflens').upper()}] {severity.capitalize()}",
                    "message": f.get("message", ""),
                    "raw_details": f.get("suggestion", ""),
                },
            )
        )

    # Sort by severity (critical first), then drop the sort key.
    ranked.sort(key=lambda item: item[0])
    annotations = [a for _, a in ranked]

    return annotations


def findings_to_review_comments(analysis: AnalysisResult) -> list[dict]:
    """Convert high-severity findings into PR review inline comments."""
    comments = []

    for f in _collect_all_findings(analysis):
        severity = f.get("severity", "info")
        if severity not in ("error", "critical"):
            continue

        line = f.get("line_number")
        path = f.get("file_path", "")
        if not line or not path:
            continue

        # Strip leading path prefixes (e.g. "b/file.py" → "file.py")
        if path.startswith("b/"):
            path = path[2:]

        emoji = SEVERITY_EMOJI.get(severity, "")
        analyzer = f.get("analyzer", "").upper()
        body_parts = [
            f"{emoji} **[{analyzer}]** {f.get('message', '')}",
        ]
        if f.get("suggestion"):
            body_parts.append(f"\n💡 **Suggestion:** {f['suggestion']}")
        if f.get("times_seen_before"):
            body_parts.append(f"\n🔁 {seen_before_label(f)} in earlier reviews.")

        # GitHub's review API requires `side` and `subject_type` when
        # using absolute line numbers instead of diff hunk positions.
        comments.append(
            {
                "path": path,
                "line": line,
                "side": "RIGHT",
                "body": "\n".join(body_parts),
            }
        )

    return comments


def seen_before_label(finding: dict) -> str:
    """'seen 3 times before', 'seen once before' or 'new'."""
    count = finding.get("times_seen_before") or 0
    if count == 0:
        return "new"
    if count == 1:
        return "seen once before"
    return f"seen {count} times before"


def risk_level_to_status_state(risk_level: str) -> str:
    """Map DiffLens risk level to GitHub commit status state."""
    mapping = {
        "low": "success",
        "medium": "success",
        "high": "failure",
        "critical": "failure",
    }
    return mapping.get(risk_level.lower(), "success")


def risk_level_to_conclusion(risk_level: str) -> str:
    """Map DiffLens risk level to GitHub Check Run conclusion."""
    mapping = {
        "low": "success",
        "medium": "neutral",
        "high": "failure",
        "critical": "failure",
    }
    return mapping.get(risk_level.lower(), "neutral")


def _risk_emoji(level: str) -> str:
    mapping = {
        "low": "🟢",
        "medium": "🟡",
        "high": "🟠",
        "critical": "🔴",
    }
    return mapping.get(level.lower(), "⚪")


def _collect_all_findings(analysis: AnalysisResult) -> list[dict]:
    """Collect all findings with analyzer tag."""
    findings = []
    for f in analysis.complexity_findings:
        findings.append({**f, "analyzer": "complexity"})
    for f in analysis.naming_findings:
        findings.append({**f, "analyzer": "naming"})
    for f in analysis.bug_risk_findings:
        findings.append({**f, "analyzer": "bug_risk"})
    return findings


def _collect_top_findings(analysis: AnalysisResult, limit: int = 10) -> list[dict]:
    """Collect top findings sorted by severity."""
    all_findings = _collect_all_findings(analysis)
    severity_order = {"critical": 0, "error": 1, "warning": 2, "info": 3}
    all_findings.sort(key=lambda f: severity_order.get(f.get("severity", "info"), 4))
    return all_findings[:limit]
