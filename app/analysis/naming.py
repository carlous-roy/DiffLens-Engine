"""Naming convention validator for Python and Java code."""
from dataclasses import dataclass
from typing import Optional
import re

@dataclass
class NamingFinding:
    """Result of naming convention check."""
    name: str
    kind: str  # function, variable, class, constant
    line_number: int
    file_path: str
    severity: str
    message: str
    suggestion: Optional[str] = None

# Patterns
SNAKE_CASE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
SCREAMING_SNAKE = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$")
PASCAL_CASE = re.compile(r"^[A-Z][a-zA-Z0-9]*$")
CAMEL_CASE = re.compile(r"^[a-z][a-zA-Z0-9]*$")
PRIVATE_PREFIX = re.compile(r"^_[a-z][a-z0-9]*(_[a-z0-9]+)*$")

# Python dunder methods
DUNDER = re.compile(r"^__[a-z][a-z0-9]*(_[a-z0-9]+)*__$")

def _to_snake_case(name: str) -> str:
    """Convert a name to snake_case suggestion."""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

def _to_camel_case(name: str) -> str:
    """Convert snake_case to camelCase."""
    parts = name.split("_")
    return parts[0].lower() + "".join(p.capitalize() for p in parts[1:])

def check_python_naming(source_code: str, file_path: str) -> list[NamingFinding]:
    """Check Python naming conventions: PEP 8 expects snake_case for functions
    and variables, PascalCase for classes, and SCREAMING_SNAKE_CASE for
    module-level constants."""
    findings: list[NamingFinding] = []
    lines = source_code.split("\n")

    for i, line in enumerate(lines, start=1):
        stripped = line.strip()

        # Skip comments and empty lines
        if not stripped or stripped.startswith("#"):
            continue

        # Class definitions
        class_match = re.match(r"^class\s+(\w+)", stripped)
        if class_match:
            name = class_match.group(1)
            if not PASCAL_CASE.match(name):
                findings.append(NamingFinding(
                    name=name, kind="class", line_number=i,
                    file_path=file_path, severity="warning",
                    message=f"Class '{name}' should use PascalCase.",
                    suggestion=f"Rename to '{name[0].upper()}{name[1:]}'.",
                ))
            continue

        # Function/method definitions
        func_match = re.match(r"^\s*def\s+(\w+)", stripped)
        if func_match:
            name = func_match.group(1)
            # Allow dunder methods and private methods
            if DUNDER.match(name) or PRIVATE_PREFIX.match(name):
                continue
            if not SNAKE_CASE.match(name):
                findings.append(NamingFinding(
                    name=name, kind="function", line_number=i,
                    file_path=file_path, severity="warning",
                    message=f"Function '{name}' should use snake_case.",
                    suggestion=f"Rename to '{_to_snake_case(name)}'.",
                ))
            continue

        # Module-level constants (ALL_CAPS assignment at indent level 0)
        const_match = re.match(r"^([A-Z_][A-Z0-9_]*)\s*=", line)
        if const_match:
            name = const_match.group(1)
            if not SCREAMING_SNAKE.match(name):
                findings.append(NamingFinding(
                    name=name, kind="constant", line_number=i,
                    file_path=file_path, severity="info",
                    message=f"Constant '{name}' should use SCREAMING_SNAKE_CASE.",
                ))

    return findings

def check_java_naming(source_code: str, file_path: str) -> list[NamingFinding]:
    """Check Java naming conventions: PascalCase for classes, interfaces and
    enums, camelCase for methods and fields, and SCREAMING_SNAKE_CASE for
    static final constants."""
    findings: list[NamingFinding] = []
    lines = source_code.split("\n")

    for i, line in enumerate(lines, start=1):
        stripped = line.strip()

        if not stripped or stripped.startswith("//") or stripped.startswith("*"):
            continue

        # Class / Interface / Enum
        class_match = re.match(
            r"(?:public\s+|private\s+|protected\s+)?(?:abstract\s+|final\s+)?"
            r"(?:class|interface|enum)\s+(\w+)", stripped
        )
        if class_match:
            name = class_match.group(1)
            if not PASCAL_CASE.match(name):
                findings.append(NamingFinding(
                    name=name, kind="class", line_number=i,
                    file_path=file_path, severity="warning",
                    message=f"Class '{name}' should use PascalCase.",
                ))
            continue

        # Constants (static final)
        const_match = re.match(
            r".*static\s+final\s+\w+\s+(\w+)\s*=", stripped
        )
        if const_match:
            name = const_match.group(1)
            if not SCREAMING_SNAKE.match(name):
                findings.append(NamingFinding(
                    name=name, kind="constant", line_number=i,
                    file_path=file_path, severity="warning",
                    message=f"Constant '{name}' should use SCREAMING_SNAKE_CASE.",
                    suggestion=f"Rename to '{name.upper()}'.",
                ))
            continue

        # Method declarations
        method_match = re.match(
            r"(?:public\s+|private\s+|protected\s+)?(?:static\s+)?(?:abstract\s+)?"
            r"(?:synchronized\s+)?(?:final\s+)?(?:\w+(?:<[^>]+>)?)\s+(\w+)\s*\(", stripped
        )
        if method_match:
            name = method_match.group(1)
            # Skip constructors (PascalCase is expected)
            if PASCAL_CASE.match(name):
                continue
            if not CAMEL_CASE.match(name):
                findings.append(NamingFinding(
                    name=name, kind="method", line_number=i,
                    file_path=file_path, severity="warning",
                    message=f"Method '{name}' should use camelCase.",
                    suggestion=f"Rename to '{_to_camel_case(name)}'.",
                ))

    return findings
