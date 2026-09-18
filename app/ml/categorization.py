"""Auto-categorization — classifies findings by impact category."""

import logging
import re
from dataclasses import asdict, dataclass

logger = logging.getLogger(__name__)


@dataclass
class CategorizedFinding:
    """A finding with its assigned category and confidence."""

    original_message: str
    category: str  # security, correctness, performance, maintainability, style
    confidence: float  # 0.0 to 1.0
    reasoning: str
    analyzer: str
    severity: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CategorizationResult:
    """Result of auto-categorizing a set of findings."""

    categorized: list[CategorizedFinding]
    summary: dict  # count per category
    method: str  # "keyword" or "llm"

    def to_dict(self) -> dict:
        return {
            "categorized": [c.to_dict() for c in self.categorized],
            "summary": self.summary,
            "method": self.method,
        }


# Keyword-based classification rules
# Each rule: (category, confidence, list of patterns)
CLASSIFICATION_RULES = [
    # Security
    (
        "security",
        0.95,
        [
            re.compile(r"eval\(\)|exec\(\)", re.IGNORECASE),
            re.compile(r"security risk", re.IGNORECASE),
            re.compile(r"injection", re.IGNORECASE),
            re.compile(r"unsafe|insecure", re.IGNORECASE),
            re.compile(r"sql.*injection|xss|csrf", re.IGNORECASE),
            re.compile(r"hardcoded.*(password|secret|token)", re.IGNORECASE),
        ],
    ),
    # Correctness
    (
        "correctness",
        0.90,
        [
            re.compile(r"mutable default", re.IGNORECASE),
            re.compile(r"\.equals\(null\)", re.IGNORECASE),
            re.compile(r"== None|is None", re.IGNORECASE),
            re.compile(r"string comparison using", re.IGNORECASE),
            re.compile(r"bare except|silently swallowed", re.IGNORECASE),
            re.compile(r"null pointer|null reference", re.IGNORECASE),
            re.compile(r"off.by.one|index.*bound", re.IGNORECASE),
            re.compile(r"always returns false", re.IGNORECASE),
        ],
    ),
    # Performance
    (
        "performance",
        0.85,
        [
            re.compile(r"O\(n\^2\)|quadratic|exponential", re.IGNORECASE),
            re.compile(r"memory leak|resource leak", re.IGNORECASE),
            re.compile(r"unnecessary.*loop|redundant.*iteration", re.IGNORECASE),
            re.compile(r"cach(e|ing)", re.IGNORECASE),
        ],
    ),
    # Maintainability
    (
        "maintainability",
        0.85,
        [
            re.compile(r"refactor", re.IGNORECASE),
            re.compile(r"cyclomatic complexity", re.IGNORECASE),
            re.compile(r"nesting depth", re.IGNORECASE),
            re.compile(r"global.*keyword|global state", re.IGNORECASE),
            re.compile(r"wildcard import", re.IGNORECASE),
            re.compile(r"TODO|FIXME|HACK|XXX", re.IGNORECASE),
            re.compile(r"too (long|complex|large)", re.IGNORECASE),
            re.compile(r"dead code|unused", re.IGNORECASE),
            re.compile(r"consider using a (class|function|method)", re.IGNORECASE),
        ],
    ),
    # Style
    (
        "style",
        0.90,
        [
            re.compile(r"snake_case|camelCase|PascalCase|SCREAMING_SNAKE", re.IGNORECASE),
            re.compile(r"naming convention", re.IGNORECASE),
            re.compile(r"should use.*Case", re.IGNORECASE),
            re.compile(r"rename to", re.IGNORECASE),
            re.compile(r"logging framework|System\.out", re.IGNORECASE),
        ],
    ),
]

# Analyzer-to-default-category mapping (fallback)
ANALYZER_DEFAULTS = {
    "complexity": ("maintainability", 0.7),
    "naming": ("style", 0.8),
    "bug_risk": ("correctness", 0.6),
}


def _classify_single(message: str, analyzer: str, severity: str) -> tuple[str, float, str]:
    """Classify a single finding message."""
    combined_text = f"{message} [{analyzer}] [{severity}]"

    # Check rules in order (first match wins for specificity)
    best_match = None
    best_confidence = 0.0
    best_reasoning = ""

    for category, confidence, patterns in CLASSIFICATION_RULES:
        for pattern in patterns:
            if pattern.search(combined_text):
                match_text = pattern.pattern[:50]
                if confidence > best_confidence:
                    best_match = category
                    best_confidence = confidence
                    best_reasoning = f"Matched pattern: {match_text}"
                break  # One pattern match per category is enough

    if best_match:
        return best_match, best_confidence, best_reasoning

    # Fallback to analyzer-based default
    default_cat, default_conf = ANALYZER_DEFAULTS.get(analyzer, ("maintainability", 0.5))
    return default_cat, default_conf, f"Default category for '{analyzer}' analyzer"


def categorize_findings(findings: list[dict]) -> CategorizationResult:
    """Auto-categorize a list of findings."""
    categorized = []
    category_counts = {
        "security": 0,
        "correctness": 0,
        "performance": 0,
        "maintainability": 0,
        "style": 0,
    }

    for f in findings:
        message = f.get("message", "")
        analyzer = f.get("analyzer", "")
        severity = f.get("severity", "info")

        category, confidence, reasoning = _classify_single(message, analyzer, severity)
        category_counts[category] = category_counts.get(category, 0) + 1

        categorized.append(
            CategorizedFinding(
                original_message=message,
                category=category,
                confidence=confidence,
                reasoning=reasoning,
                analyzer=analyzer,
                severity=severity,
            )
        )

    return CategorizationResult(
        categorized=categorized,
        summary=category_counts,
        method="keyword",
    )
