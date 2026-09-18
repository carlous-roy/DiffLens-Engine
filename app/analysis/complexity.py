"""Complexity analyzer: cyclomatic complexity and nesting depth per function.

Both metrics are computed on the Tree-sitter syntax tree. A function is
measured when its definition line is part of the change; the count covers
the function text visible in the diff view it was given.
"""

from dataclasses import dataclass

from app.analysis.diff_parser import SourceView
from app.analysis.syntax import TREE_SITTER_AVAILABLE, iter_nodes, node_text, parse


@dataclass
class ComplexityFinding:
    """Result of complexity analysis on a function/method."""

    function_name: str
    line_number: int
    complexity: int
    file_path: str
    severity: str  # info, warning, error, critical
    message: str
    suggestion: str | None = None
    nesting_depth: int = 0
    metric: str = "cyclomatic_complexity"  # or "nesting_depth"


# Nodes that add one to cyclomatic complexity: each is a decision point.
PYTHON_BRANCH_NODES = frozenset(
    {
        "if_statement",
        "elif_clause",
        "for_statement",
        "while_statement",
        "except_clause",
        "with_statement",
        "assert_statement",
        "case_clause",
        "boolean_operator",  # `and` / `or`
        "conditional_expression",  # ternary
        "list_comprehension",
        "set_comprehension",
        "dictionary_comprehension",
        "generator_expression",
    }
)

JAVA_BRANCH_NODES = frozenset(
    {
        "if_statement",
        "for_statement",
        "enhanced_for_statement",
        "while_statement",
        "do_statement",
        "catch_clause",
        "switch_block_statement_group",  # `case ...:` groups
        "switch_rule",  # `case ... ->`
        "ternary_expression",
        "binary_expression",  # only && and || count, see _is_short_circuit
    }
)

# Statements that open a new nesting level.
PYTHON_NESTING_NODES = frozenset(
    {
        "if_statement",
        "for_statement",
        "while_statement",
        "try_statement",
        "with_statement",
        "match_statement",
    }
)

JAVA_NESTING_NODES = frozenset(
    {
        "if_statement",
        "for_statement",
        "enhanced_for_statement",
        "while_statement",
        "do_statement",
        "try_statement",
        "try_with_resources_statement",
        "switch_expression",
        "synchronized_statement",
    }
)

# Definitions that own their own metrics: the walk does not descend into them
# when measuring the enclosing function.
PYTHON_FUNCTION_NODES = frozenset({"function_definition"})
JAVA_FUNCTION_NODES = frozenset({"method_declaration", "constructor_declaration"})
PYTHON_SCOPE_BOUNDARIES = PYTHON_FUNCTION_NODES | {"class_definition"}
JAVA_SCOPE_BOUNDARIES = JAVA_FUNCTION_NODES | {"class_declaration"}

_LANGUAGE_TABLES = {
    "python": (
        PYTHON_FUNCTION_NODES,
        PYTHON_BRANCH_NODES,
        PYTHON_NESTING_NODES,
        PYTHON_SCOPE_BOUNDARIES,
    ),
    "java": (JAVA_FUNCTION_NODES, JAVA_BRANCH_NODES, JAVA_NESTING_NODES, JAVA_SCOPE_BOUNDARIES),
}

NESTING_WARNING_DEPTH = 4
NESTING_ERROR_DEPTH = 6


def _is_short_circuit(node) -> bool:
    op = node.child_by_field_name("operator")
    return op is not None and op.type in ("&&", "||")


def _measure(function_node, language: str) -> tuple[int, int]:
    """Return (cyclomatic complexity, max nesting depth) for one function.

    Nested function and class definitions are skipped: they are reported on
    their own. An `else if` chain in Java is one level, not one per branch.
    """
    _, branch_nodes, nesting_nodes, boundaries = _LANGUAGE_TABLES[language]
    complexity = 1
    max_depth = 0
    # Stack entries: (node, nesting depth of the node itself)
    stack = [(child, 0) for child in reversed(function_node.children)]
    while stack:
        node, depth = stack.pop()
        ntype = node.type
        if ntype in boundaries:
            continue

        if ntype in branch_nodes:
            if language != "java" or ntype != "binary_expression" or _is_short_circuit(node):
                complexity += 1

        child_depth = depth
        if ntype in nesting_nodes:
            chained = (
                language == "java"
                and ntype == "if_statement"
                and node.parent is not None
                and node.parent.type == "if_statement"
                and node.parent.child_by_field_name("alternative") == node
            )
            if not chained:
                child_depth = depth + 1
                max_depth = max(max_depth, child_depth)

        stack.extend((child, child_depth) for child in reversed(node.children))
    return complexity, max_depth


def _severity_for_complexity(complexity: int) -> str:
    """Map complexity score to severity level."""
    if complexity <= 5:
        return "info"
    elif complexity <= 10:
        return "warning"
    elif complexity <= 20:
        return "error"
    return "critical"


def _severity_for_nesting(depth: int) -> str | None:
    if depth >= NESTING_ERROR_DEPTH:
        return "error"
    if depth >= NESTING_WARNING_DEPTH:
        return "warning"
    return None


def analyze_complexity(
    source_code: str,
    file_path: str,
    language: str,
    view: SourceView | None = None,
) -> list[ComplexityFinding]:
    """Measure every function whose definition line is part of the change.

    `view` maps lines of `source_code` back to file line numbers and says
    which lines were changed; without it the text is treated as a complete,
    entirely new file.
    """
    if not TREE_SITTER_AVAILABLE:
        return [
            ComplexityFinding(
                function_name="<unavailable>",
                line_number=0,
                complexity=0,
                file_path=file_path,
                severity="info",
                message="Tree-sitter not available; skipping complexity analysis.",
            )
        ]
    if language not in _LANGUAGE_TABLES:
        return []

    if view is None:
        view = SourceView.from_text(source_code)
    function_nodes = _LANGUAGE_TABLES[language][0]
    data = source_code.encode("utf-8")
    tree = parse(data, language)
    findings: list[ComplexityFinding] = []

    for node in iter_nodes(tree.root_node):
        if node.type not in function_nodes:
            continue
        local_line = node.start_point[0] + 1
        if not view.is_changed(local_line):
            continue
        name_node = node.child_by_field_name("name")
        func_name = node_text(name_node, data) if name_node else "<anonymous>"
        line = view.map_line(local_line)

        complexity, depth = _measure(node, language)
        severity = _severity_for_complexity(complexity)
        suggestion = None
        if complexity > 10:
            suggestion = (
                f"Consider refactoring '{func_name}' into smaller functions. "
                f"Extract conditional branches or loop bodies into helper methods."
            )
        findings.append(
            ComplexityFinding(
                function_name=func_name,
                line_number=line,
                complexity=complexity,
                file_path=file_path,
                severity=severity,
                message=f"Function '{func_name}' has cyclomatic complexity of {complexity}.",
                suggestion=suggestion,
                nesting_depth=depth,
            )
        )

        nesting_severity = _severity_for_nesting(depth)
        if nesting_severity:
            findings.append(
                ComplexityFinding(
                    function_name=func_name,
                    line_number=line,
                    complexity=complexity,
                    file_path=file_path,
                    severity=nesting_severity,
                    message=f"Function '{func_name}' has a nesting depth of {depth}.",
                    suggestion=(
                        f"Flatten '{func_name}': return early, invert conditions, or move "
                        f"the inner blocks into helper functions."
                    ),
                    nesting_depth=depth,
                    metric="nesting_depth",
                )
            )

    return findings
