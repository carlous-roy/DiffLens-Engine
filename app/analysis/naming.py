"""Naming convention checks for Python (PEP 8) and Java, driven by the syntax tree.

Names are taken from definition nodes, so a `def` inside a string or a
comment is never checked, constructors are never mistaken for methods, and
every finding points at the line the definition starts on.
"""

import re
from dataclasses import dataclass

from app.analysis.diff_parser import SourceView
from app.analysis.syntax import TREE_SITTER_AVAILABLE, iter_nodes, node_text, parse


@dataclass
class NamingFinding:
    """Result of naming convention check."""

    name: str
    kind: str  # function, method, variable, parameter, class, constant, field
    line_number: int
    file_path: str
    severity: str
    message: str
    suggestion: str | None = None


# Patterns
SNAKE_CASE = re.compile(r"^_*[a-z][a-z0-9]*(_[a-z0-9]+)*_*$")
SCREAMING_SNAKE = re.compile(r"^_*[A-Z][A-Z0-9]*(_[A-Z0-9]+)*_*$")
PASCAL_CASE = re.compile(r"^_*[A-Z][a-zA-Z0-9]*$")
CAMEL_CASE = re.compile(r"^_*[a-z][a-zA-Z0-9]*$")
DUNDER = re.compile(r"^__[a-z][a-z0-9]*(_[a-z0-9]+)*__$")

# Python names that are conventionally capitalised without being classes
# (type variables and aliases follow CapWords under PEP 8).
_PY_CAPITALISED_OK = PASCAL_CASE


def _to_snake_case(name: str) -> str:
    """Convert a name to snake_case suggestion."""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _to_camel_case(name: str) -> str:
    """Convert snake_case to camelCase."""
    parts = [p for p in name.split("_") if p]
    if not parts:
        return name
    return parts[0].lower() + "".join(p.capitalize() for p in parts[1:])


def _to_pascal_case(name: str) -> str:
    parts = [p for p in name.split("_") if p]
    if not parts:
        return name
    return "".join(p[0].upper() + p[1:] for p in parts)


def _is_python_constant(name: str) -> bool:
    return SCREAMING_SNAKE.match(name) is not None


def check_python_naming(
    source_code: str, file_path: str, view: SourceView | None = None
) -> list[NamingFinding]:
    """Check Python names: snake_case for functions, parameters and variables,
    PascalCase for classes, SCREAMING_SNAKE_CASE for module-level constants."""
    if not TREE_SITTER_AVAILABLE:
        return []
    if view is None:
        view = SourceView.from_text(source_code)
    data = source_code.encode("utf-8")
    tree = parse(data, "python")
    findings: list[NamingFinding] = []

    def report(node, name: str, kind: str, severity: str, message: str, suggestion=None):
        local_line = node.start_point[0] + 1
        if not view.is_changed(local_line):
            return
        findings.append(
            NamingFinding(
                name=name,
                kind=kind,
                line_number=view.map_line(local_line),
                file_path=file_path,
                severity=severity,
                message=message,
                suggestion=suggestion,
            )
        )

    for node in iter_nodes(tree.root_node):
        ntype = node.type
        if ntype == "class_definition":
            name_node = node.child_by_field_name("name")
            if name_node is None:
                continue
            name = node_text(name_node, data)
            if not PASCAL_CASE.match(name):
                report(
                    name_node,
                    name,
                    "class",
                    "warning",
                    f"Class '{name}' should use PascalCase.",
                    f"Rename to '{_to_pascal_case(name)}'.",
                )

        elif ntype == "function_definition":
            name_node = node.child_by_field_name("name")
            if name_node is None:
                continue
            name = node_text(name_node, data)
            if DUNDER.match(name) or SNAKE_CASE.match(name):
                pass
            else:
                report(
                    name_node,
                    name,
                    "function",
                    "warning",
                    f"Function '{name}' should use snake_case.",
                    f"Rename to '{_to_snake_case(name)}'.",
                )
            params = node.child_by_field_name("parameters")
            for param in params.children if params else []:
                ident = _python_parameter_identifier(param)
                if ident is None:
                    continue
                pname = node_text(ident, data)
                if not SNAKE_CASE.match(pname) and not _is_python_constant(pname):
                    report(
                        ident,
                        pname,
                        "parameter",
                        "info",
                        f"Parameter '{pname}' should use snake_case.",
                        f"Rename to '{_to_snake_case(pname)}'.",
                    )

        elif ntype == "assignment":
            left = node.child_by_field_name("left")
            if left is None or left.type != "identifier":
                continue
            name = node_text(left, data)
            module_level = (
                node.parent is not None
                and node.parent.type == "expression_statement"
                and node.parent.parent is not None
                and node.parent.parent.type == "module"
            )
            if (
                SNAKE_CASE.match(name)
                or _is_python_constant(name)
                or _PY_CAPITALISED_OK.match(name)
            ):
                continue
            if module_level and name[0].isupper():
                report(
                    left,
                    name,
                    "constant",
                    "info",
                    f"Constant '{name}' should use SCREAMING_SNAKE_CASE.",
                    f"Rename to '{name.upper()}'.",
                )
            else:
                report(
                    left,
                    name,
                    "variable",
                    "warning",
                    f"Variable '{name}' should use snake_case.",
                    f"Rename to '{_to_snake_case(name)}'.",
                )

    return findings


def _python_parameter_identifier(param):
    """Return the identifier node that names a parameter, or None."""
    if param.type == "identifier":
        return param
    if param.type in ("default_parameter", "typed_default_parameter"):
        return param.child_by_field_name("name")
    if param.type == "typed_parameter":
        for child in param.children:
            if child.type == "identifier":
                return child
    if param.type in ("list_splat_pattern", "dictionary_splat_pattern"):
        for child in param.children:
            if child.type == "identifier":
                return child
    return None


_JAVA_TYPE_DECLARATIONS = frozenset(
    {
        "class_declaration",
        "interface_declaration",
        "enum_declaration",
        "record_declaration",
        "annotation_type_declaration",
    }
)


def _java_modifiers(node) -> set[str]:
    for child in node.children:
        if child.type == "modifiers":
            return {m.type for m in child.children}
    return set()


def check_java_naming(
    source_code: str, file_path: str, view: SourceView | None = None
) -> list[NamingFinding]:
    """Check Java names: PascalCase for types, camelCase for methods, fields
    and local variables, SCREAMING_SNAKE_CASE for static final constants."""
    if not TREE_SITTER_AVAILABLE:
        return []
    if view is None:
        view = SourceView.from_text(source_code)
    data = source_code.encode("utf-8")
    tree = parse(data, "java")
    findings: list[NamingFinding] = []

    def report(node, name: str, kind: str, severity: str, message: str, suggestion=None):
        local_line = node.start_point[0] + 1
        if not view.is_changed(local_line):
            return
        findings.append(
            NamingFinding(
                name=name,
                kind=kind,
                line_number=view.map_line(local_line),
                file_path=file_path,
                severity=severity,
                message=message,
                suggestion=suggestion,
            )
        )

    for node in iter_nodes(tree.root_node):
        ntype = node.type
        if ntype in _JAVA_TYPE_DECLARATIONS:
            name_node = node.child_by_field_name("name")
            if name_node is None:
                continue
            name = node_text(name_node, data)
            if not PASCAL_CASE.match(name):
                report(
                    name_node,
                    name,
                    "class",
                    "warning",
                    f"Class '{name}' should use PascalCase.",
                    f"Rename to '{_to_pascal_case(name)}'.",
                )

        elif ntype == "method_declaration":
            name_node = node.child_by_field_name("name")
            if name_node is None:
                continue
            name = node_text(name_node, data)
            if not CAMEL_CASE.match(name):
                report(
                    name_node,
                    name,
                    "method",
                    "warning",
                    f"Method '{name}' should use camelCase.",
                    f"Rename to '{_to_camel_case(name)}'.",
                )

        elif ntype in ("field_declaration", "local_variable_declaration"):
            modifiers = _java_modifiers(node)
            # A hunk from inside a class body parses without its class, so a
            # field shows up as a local declaration; `static final` still
            # identifies it as a constant (locals cannot be static).
            is_constant = {"static", "final"} <= modifiers
            for declarator in node.children:
                if declarator.type != "variable_declarator":
                    continue
                name_node = declarator.child_by_field_name("name")
                if name_node is None:
                    continue
                name = node_text(name_node, data)
                if is_constant:
                    if not SCREAMING_SNAKE.match(name):
                        report(
                            name_node,
                            name,
                            "constant",
                            "warning",
                            f"Constant '{name}' should use SCREAMING_SNAKE_CASE.",
                            f"Rename to '{name.upper()}'.",
                        )
                elif not CAMEL_CASE.match(name) and not SCREAMING_SNAKE.match(name):
                    kind = "field" if ntype == "field_declaration" else "variable"
                    report(
                        name_node,
                        name,
                        kind,
                        "warning",
                        f"{kind.capitalize()} '{name}' should use camelCase.",
                        f"Rename to '{_to_camel_case(name)}'.",
                    )

    return findings
