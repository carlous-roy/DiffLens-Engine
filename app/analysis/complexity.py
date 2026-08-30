"""Complexity analyzer that uses Tree-sitter AST parsing to calculate the
cyclomatic complexity of each function and method in a source file."""
from dataclasses import dataclass
from typing import Optional

try:
    import tree_sitter_python as tspython
    import tree_sitter_java as tsjava
    from tree_sitter import Language, Parser

    PY_LANGUAGE = Language(tspython.language())
    JAVA_LANGUAGE = Language(tsjava.language())
    TREE_SITTER_AVAILABLE = True
except Exception:
    # Fallback: try older API style
    try:
        from tree_sitter import Language, Parser
        import tree_sitter_python as tspython
        import tree_sitter_java as tsjava

        PY_LANGUAGE = Language(tspython.language())
        JAVA_LANGUAGE = Language(tsjava.language())
        TREE_SITTER_AVAILABLE = True
    except Exception:
        TREE_SITTER_AVAILABLE = False
        PY_LANGUAGE = None
        JAVA_LANGUAGE = None

@dataclass
class ComplexityFinding:
    """Result of complexity analysis on a function/method."""
    function_name: str
    line_number: int
    complexity: int
    file_path: str
    severity: str  # info, warning, error, critical
    message: str
    suggestion: Optional[str] = None

# Nodes that add to cyclomatic complexity
PYTHON_BRANCH_NODES = {
    "if_statement", "elif_clause", "for_statement", "while_statement",
    "except_clause", "with_statement", "assert_statement",
    "boolean_operator",  # `and` / `or`
    "conditional_expression",  # ternary
    "list_comprehension", "set_comprehension", "dictionary_comprehension",
    "generator_expression",
}

JAVA_BRANCH_NODES = {
    "if_statement", "for_statement", "enhanced_for_statement",
    "while_statement", "do_statement", "catch_clause",
    "switch_expression", "ternary_expression",
    "binary_expression",  # we check for && and || specifically
}

def _count_complexity(node, branch_nodes: set, language: str) -> int:
    """Recursively count branching nodes in an AST subtree."""
    count = 0
    if node.type in branch_nodes:
        # For Java binary_expression, only count && and ||
        if language == "java" and node.type == "binary_expression":
            op_node = node.child_by_field_name("operator")
            if op_node and op_node.type in ("&&", "||"):
                count += 1
        else:
            count += 1
    for child in node.children:
        count += _count_complexity(child, branch_nodes, language)
    return count

def _severity_for_complexity(complexity: int) -> str:
    """Map complexity score to severity level."""
    if complexity <= 5:
        return "info"
    elif complexity <= 10:
        return "warning"
    elif complexity <= 20:
        return "error"
    return "critical"

def analyze_complexity(source_code: str, file_path: str, language: str) -> list[ComplexityFinding]:
    """Analyze cyclomatic complexity of functions/methods in source code."""
    if not TREE_SITTER_AVAILABLE:
        return [ComplexityFinding(
            function_name="<unavailable>",
            line_number=0,
            complexity=0,
            file_path=file_path,
            severity="info",
            message="Tree-sitter not available; skipping complexity analysis.",
        )]

    parser = Parser()

    if language == "python":
        parser.language = PY_LANGUAGE
        func_node_types = {"function_definition"}
        branch_nodes = PYTHON_BRANCH_NODES
    elif language == "java":
        parser.language = JAVA_LANGUAGE
        func_node_types = {"method_declaration", "constructor_declaration"}
        branch_nodes = JAVA_BRANCH_NODES
    else:
        return []

    tree = parser.parse(bytes(source_code, "utf-8"))
    findings: list[ComplexityFinding] = []

    def _walk(node):
        if node.type in func_node_types:
            name_node = node.child_by_field_name("name")
            func_name = name_node.text.decode("utf-8") if name_node else "<anonymous>"
            line = node.start_point[0] + 1  # 0-indexed to 1-indexed

            complexity = 1 + _count_complexity(node, branch_nodes, language)
            severity = _severity_for_complexity(complexity)

            suggestion = None
            if complexity > 10:
                suggestion = (
                    f"Consider refactoring '{func_name}' into smaller functions. "
                    f"Extract conditional branches or loop bodies into helper methods."
                )

            findings.append(ComplexityFinding(
                function_name=func_name,
                line_number=line,
                complexity=complexity,
                file_path=file_path,
                severity=severity,
                message=f"Function '{func_name}' has cyclomatic complexity of {complexity}.",
                suggestion=suggestion,
            ))

        for child in node.children:
            _walk(child)

    _walk(tree.root_node)
    return findings
