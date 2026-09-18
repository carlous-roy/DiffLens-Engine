"""Bug risk detector that identifies common patterns likely to be bugs."""

import re
from dataclasses import dataclass


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


# Python bug risk patterns
PYTHON_PATTERNS: list[dict] = [
    {
        "rule_id": "PY001",
        "pattern": re.compile(r"\bexcept\s*:\s*$"),
        "severity": "warning",
        "message": (
            "Bare except clause catches all exceptions including SystemExit and KeyboardInterrupt."
        ),
        "suggestion": "Use 'except Exception:' or catch specific exceptions.",
    },
    {
        "rule_id": "PY002",
        "pattern": re.compile(r"except\s+\w+.*:\s*pass\s*$"),
        "severity": "warning",
        "message": "Exception silently swallowed with 'pass'.",
        "suggestion": "Log the exception or handle it explicitly.",
    },
    {
        "rule_id": "PY003",
        "pattern": re.compile(r"def\s+\w+\s*\([^)]*=\s*(\[\]|\{\}|\(\))"),
        "severity": "error",
        "message": (
            "Mutable default argument detected. Default mutable arguments are shared between calls."
        ),
        "suggestion": "Use None as default and initialize inside the function body.",
    },
    {
        "rule_id": "PY004",
        "pattern": re.compile(r"\b(?:is|is not)\s+(?:True|False|None)\b"),
        "severity": "info",
        "message": "Identity comparison with singleton is correct; ensure this is intentional.",
    },
    {
        "rule_id": "PY005",
        "pattern": re.compile(r"==\s*None\b|\bNone\s*=="),
        "severity": "warning",
        "message": "Use 'is None' instead of '== None' for None comparisons.",
        "suggestion": "Replace '== None' with 'is None'.",
    },
    {
        "rule_id": "PY006",
        "pattern": re.compile(r"\bglobal\s+\w+"),
        "severity": "warning",
        "message": "Use of 'global' keyword. Global state makes code harder to test and debug.",
        "suggestion": "Consider passing values as function parameters or using a class.",
    },
    {
        "rule_id": "PY007",
        "pattern": re.compile(r"#\s*TODO|#\s*FIXME|#\s*HACK|#\s*XXX", re.IGNORECASE),
        "severity": "info",
        "message": "TODO/FIXME comment found in new code.",
        "suggestion": "Ensure this is tracked in your issue tracker.",
    },
    {
        "rule_id": "PY008",
        "pattern": re.compile(r"\beval\s*\(|\bexec\s*\("),
        "severity": "critical",
        "message": "Use of eval()/exec() is a security risk.",
        "suggestion": (
            "Use ast.literal_eval() for safe evaluation or refactor to avoid dynamic execution."
        ),
    },
    {
        "rule_id": "PY009",
        "pattern": re.compile(r"import\s+\*"),
        "severity": "warning",
        "message": "Wildcard import pollutes the namespace and makes code harder to understand.",
        "suggestion": "Import specific names instead.",
    },
]

# Java bug risk patterns
JAVA_PATTERNS: list[dict] = [
    {
        "rule_id": "JV001",
        "pattern": re.compile(r"\.equals\s*\(\s*null\s*\)"),
        "severity": "error",
        "message": "Calling .equals(null) always returns false. Use '== null' instead.",
        "suggestion": "Replace with '== null' check.",
    },
    {
        "rule_id": "JV002",
        "pattern": re.compile(r"catch\s*\(\s*Exception\s+\w+\s*\)\s*\{\s*\}"),
        "severity": "warning",
        "message": "Empty catch block silently swallows exceptions.",
        "suggestion": "Log the exception or rethrow it.",
    },
    {
        "rule_id": "JV003",
        "pattern": re.compile(r"==\s*\"[^\"]*\"|\"\w*\"\s*=="),
        "severity": "warning",
        "message": "String comparison using '==' compares references, not values.",
        "suggestion": "Use .equals() for string comparison.",
    },
    {
        "rule_id": "JV004",
        "pattern": re.compile(r"System\.out\.print|System\.err\.print"),
        "severity": "info",
        "message": "Direct console output found. Consider using a logging framework.",
        "suggestion": "Use SLF4J, Log4j, or java.util.logging.",
    },
    {
        "rule_id": "JV005",
        "pattern": re.compile(r"new\s+(?:Thread|Runnable)\s*\("),
        "severity": "info",
        "message": "Manual thread creation detected.",
        "suggestion": "Consider using ExecutorService for better thread management.",
    },
    {
        "rule_id": "JV006",
        "pattern": re.compile(r"//\s*TODO|//\s*FIXME|//\s*HACK|//\s*XXX", re.IGNORECASE),
        "severity": "info",
        "message": "TODO/FIXME comment found in new code.",
        "suggestion": "Ensure this is tracked in your issue tracker.",
    },
]


def detect_bug_risks(
    lines: list[tuple[int, str]],
    file_path: str,
    language: str,
) -> list[BugRiskFinding]:
    """Scan a list of (line_number, content) tuples for bug risk patterns."""
    if language == "python":
        patterns = PYTHON_PATTERNS
    elif language == "java":
        patterns = JAVA_PATTERNS
    else:
        return []

    findings: list[BugRiskFinding] = []

    for line_num, content in lines:
        for pat in patterns:
            match = pat["pattern"].search(content)
            if match:
                findings.append(
                    BugRiskFinding(
                        rule_id=pat["rule_id"],
                        line_number=line_num,
                        file_path=file_path,
                        severity=pat["severity"],
                        message=pat["message"],
                        suggestion=pat.get("suggestion"),
                        matched_text=match.group(0),
                    )
                )

    return findings
