"""Bug risk rules: patterns that are often wrong, checked against code only.

Each rule is a line regex with a scope. `code` rules run on the masked
source (comments and string contents blanked from the syntax tree), so
`eval(` in a comment or inside a string literal never fires. `comment`
rules run on comment text only, for markers such as TODO.
"""

import re
from dataclasses import dataclass

from app.analysis.diff_parser import SourceView
from app.analysis.syntax import mask_comments_and_strings


@dataclass
class BugRiskFinding:
    """A potential bug risk identified in the code."""

    rule_id: str
    line_number: int
    file_path: str
    severity: str
    message: str
    suggestion: str | None = None
    matched_text: str | None = None


@dataclass(frozen=True)
class Rule:
    rule_id: str
    pattern: re.Pattern
    severity: str
    message: str
    suggestion: str | None = None
    scope: str = "code"  # "code" or "comment"


# Python bug risk rules
PYTHON_RULES: list[Rule] = [
    Rule(
        "PY001",
        re.compile(r"\bexcept\s*:\s*$"),
        "warning",
        "Bare except clause catches all exceptions including SystemExit and KeyboardInterrupt.",
        "Use 'except Exception:' or catch specific exceptions.",
    ),
    Rule(
        "PY002",
        re.compile(r"\bexcept\b[^:]*:\s*pass\s*$"),
        "warning",
        "Exception silently swallowed with 'pass'.",
        "Log the exception or handle it explicitly.",
    ),
    Rule(
        "PY003",
        re.compile(r"\bdef\s+\w+\s*\([^)]*=\s*(\[\]|\{\}|\(\))"),
        "error",
        "Mutable default argument detected. Default mutable arguments are shared between calls.",
        "Use None as default and initialize inside the function body.",
    ),
    Rule(
        "PY004",
        re.compile(r"\b(?:is|is not)\s+(?:True|False)\b"),
        "info",
        "Identity comparison with a boolean singleton; a plain truth test is usually clearer.",
        "Use 'if x:' or 'if not x:' unless identity with True/False is required.",
    ),
    Rule(
        "PY005",
        re.compile(r"==\s*None\b|\bNone\s*==|!=\s*None\b|\bNone\s*!="),
        "warning",
        "Use 'is None' instead of '== None' for None comparisons.",
        "Replace '== None' with 'is None' (and '!= None' with 'is not None').",
    ),
    Rule(
        "PY006",
        re.compile(r"^\s*global\s+\w+"),
        "warning",
        "Use of 'global' keyword. Global state makes code harder to test and debug.",
        "Consider passing values as function parameters or using a class.",
    ),
    Rule(
        "PY007",
        re.compile(r"#\s*(?:TODO|FIXME|HACK|XXX)\b", re.IGNORECASE),
        "info",
        "TODO/FIXME comment found in new code.",
        "Ensure this is tracked in your issue tracker.",
        scope="comment",
    ),
    Rule(
        "PY008",
        re.compile(r"(?<![\w.])(?:eval|exec)\s*\("),
        "critical",
        "Use of eval()/exec() is a security risk.",
        "Use ast.literal_eval() for safe evaluation or refactor to avoid dynamic execution.",
    ),
    Rule(
        "PY009",
        re.compile(r"^\s*from\s+[\w.]+\s+import\s+\*"),
        "warning",
        "Wildcard import pollutes the namespace and makes code harder to understand.",
        "Import specific names instead.",
    ),
]

# Java bug risk rules
JAVA_RULES: list[Rule] = [
    Rule(
        "JV001",
        re.compile(r"\.equals\s*\(\s*null\s*\)"),
        "error",
        "Calling .equals(null) always returns false. Use '== null' instead.",
        "Replace with '== null' check.",
    ),
    Rule(
        "JV002",
        re.compile(r"\bcatch\s*\([^)]*\)\s*\{\s*\}"),
        "warning",
        "Empty catch block silently swallows exceptions.",
        "Log the exception or rethrow it.",
    ),
    Rule(
        "JV003",
        re.compile(r"[=!]=\s*\"[^\"]*\"|\"[^\"]*\"\s*[=!]="),
        "warning",
        "String comparison using '==' compares references, not values.",
        "Use .equals() for string comparison.",
    ),
    Rule(
        "JV004",
        re.compile(r"\bSystem\s*\.\s*(?:out|err)\s*\.\s*print"),
        "info",
        "Direct console output found. Consider using a logging framework.",
        "Use SLF4J, Log4j, or java.util.logging.",
    ),
    Rule(
        "JV005",
        re.compile(r"\bnew\s+Thread\s*\("),
        "info",
        "Manual thread creation detected.",
        "Consider using ExecutorService for better thread management.",
    ),
    Rule(
        "JV006",
        re.compile(r"(?://|/\*|\*)\s*(?:TODO|FIXME|HACK|XXX)\b", re.IGNORECASE),
        "info",
        "TODO/FIXME comment found in new code.",
        "Ensure this is tracked in your issue tracker.",
        scope="comment",
    ),
]

_RULES = {"python": PYTHON_RULES, "java": JAVA_RULES}


def detect_bug_risks(
    source_code: str,
    file_path: str,
    language: str,
    view: SourceView | None = None,
) -> list[BugRiskFinding]:
    """Run the bug risk rules for `language` over `source_code`.

    Only changed lines of `view` produce findings (all lines when no view is
    given), and line numbers are reported in file coordinates.
    """
    rules = _RULES.get(language)
    if not rules:
        return []
    if view is None:
        view = SourceView.from_text(source_code)

    masked = mask_comments_and_strings(source_code, language)
    code_rules = [r for r in rules if r.scope == "code"]
    comment_rules = [r for r in rules if r.scope == "comment"]
    findings: list[BugRiskFinding] = []

    for index, line in enumerate(masked.code_lines, start=1):
        if not view.is_changed(index):
            continue
        for rule in code_rules:
            match = rule.pattern.search(line)
            if match:
                findings.append(_finding(rule, view.map_line(index), file_path, match.group(0)))

    for index, comment in masked.comments:
        if not view.is_changed(index):
            continue
        for rule in comment_rules:
            match = rule.pattern.search(comment)
            if match:
                findings.append(_finding(rule, view.map_line(index), file_path, match.group(0)))

    findings.sort(key=lambda f: (f.line_number, f.rule_id))
    return findings


def _finding(rule: Rule, line: int, file_path: str, matched: str) -> BugRiskFinding:
    return BugRiskFinding(
        rule_id=rule.rule_id,
        line_number=line,
        file_path=file_path,
        severity=rule.severity,
        message=rule.message,
        suggestion=rule.suggestion,
        matched_text=matched.strip(),
    )
