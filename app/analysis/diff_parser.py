"""Unified diff parser and raw code auto-wrapping."""
from dataclasses import dataclass, field
from typing import Optional
import re

@dataclass
class DiffHunk:
    """A single hunk (contiguous changed region) in a diff."""
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[str] = field(default_factory=list)

    @property
    def added_lines(self) -> list[tuple[int, str]]:
        """Return (line_number, content) pairs for added lines."""
        results = []
        current_line = self.new_start
        for line in self.lines:
            if line.startswith("+"):
                results.append((current_line, line[1:]))
                current_line += 1
            elif line.startswith("-"):
                continue
            else:
                current_line += 1
        return results

    @property
    def removed_lines(self) -> list[tuple[int, str]]:
        """Return (line_number, content) pairs for removed lines."""
        results = []
        current_line = self.old_start
        for line in self.lines:
            if line.startswith("-"):
                results.append((current_line, line[1:]))
                current_line += 1
            elif line.startswith("+"):
                continue
            else:
                current_line += 1
        return results

@dataclass
class FileDiff:
    """All changes to a single file within a diff."""
    old_path: Optional[str]
    new_path: Optional[str]
    hunks: list[DiffHunk] = field(default_factory=list)
    is_new_file: bool = False
    is_deleted_file: bool = False
    is_renamed: bool = False

    @property
    def path(self) -> str:
        return self.new_path or self.old_path or "unknown"

    @property
    def language(self) -> Optional[str]:
        """Infer language from file extension."""
        ext_map = {
            ".py": "python", ".java": "java", ".js": "javascript",
            ".ts": "typescript", ".go": "go", ".rs": "rust",
            ".cpp": "cpp", ".c": "c", ".rb": "ruby",
        }
        for ext, lang in ext_map.items():
            if self.path.endswith(ext):
                return lang
        return None

    @property
    def all_added_content(self) -> str:
        """Concatenate all added lines into a single string."""
        lines = []
        for hunk in self.hunks:
            for _, content in hunk.added_lines:
                lines.append(content)
        return "\n".join(lines)

# Diff parser

HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

def parse_diff(diff_text: str) -> list[FileDiff]:
    """Parse a unified diff string into FileDiff objects."""
    files: list[FileDiff] = []
    current_file: Optional[FileDiff] = None
    current_hunk: Optional[DiffHunk] = None

    lines = diff_text.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]

        # New file diff header
        if line.startswith("diff --git"):
            if current_file is not None:
                files.append(current_file)
            current_file = FileDiff(old_path=None, new_path=None)
            current_hunk = None
            i += 1
            continue

        # File mode indicators
        if line.startswith("new file mode"):
            if current_file:
                current_file.is_new_file = True
            i += 1
            continue

        if line.startswith("deleted file mode"):
            if current_file:
                current_file.is_deleted_file = True
            i += 1
            continue

        if line.startswith("rename from") or line.startswith("rename to"):
            if current_file:
                current_file.is_renamed = True
            i += 1
            continue

        # Old file path
        if line.startswith("--- "):
            if current_file:
                path = line[4:]
                if path.startswith("a/"):
                    path = path[2:]
                current_file.old_path = path if path != "/dev/null" else None
            i += 1
            continue

        # New file path
        if line.startswith("+++ "):
            if current_file:
                path = line[4:]
                if path.startswith("b/"):
                    path = path[2:]
                current_file.new_path = path if path != "/dev/null" else None
            i += 1
            continue

        # Hunk header
        hunk_match = HUNK_HEADER_RE.match(line)
        if hunk_match:
            current_hunk = DiffHunk(
                old_start=int(hunk_match.group(1)),
                old_count=int(hunk_match.group(2) or 1),
                new_start=int(hunk_match.group(3)),
                new_count=int(hunk_match.group(4) or 1),
            )
            if current_file:
                current_file.hunks.append(current_hunk)
            i += 1
            continue

        # Diff content lines (added, removed, or context)
        if current_hunk is not None and (
            line.startswith("+") or line.startswith("-") or line.startswith(" ")
        ):
            current_hunk.lines.append(line)
            i += 1
            continue

        # Skip anything else (index lines, binary notices, etc.)
        i += 1

    # Don't forget the last file
    if current_file is not None:
        files.append(current_file)

    return files

# Raw code auto-detection and wrapping

# Regex patterns to identify code by language
_LANG_HINTS = {
    "python": [
        re.compile(r"^\s*def\s+\w+\s*\("),
        re.compile(r"^\s*class\s+\w+"),
        re.compile(r"^\s*import\s+\w+"),
        re.compile(r"^\s*from\s+\w+\s+import"),
        re.compile(r"^\s*print\s*\("),
        re.compile(r"^\s*if\s+__name__\s*=="),
    ],
    "java": [
        re.compile(r"^\s*public\s+(class|interface|enum)\s+"),
        re.compile(r"^\s*(public|private|protected)\s+\w+"),
        re.compile(r"^\s*import\s+java\."),
        re.compile(r"^\s*System\.out\.print"),
    ],
}

_LANG_EXT = {
    "python": ".py", "java": ".java", "javascript": ".js",
    "typescript": ".ts", "go": ".go", "rust": ".rs",
    "cpp": ".cpp", "c": ".c", "ruby": ".rb",
}

def _guess_language(code: str) -> str:
    """Guess programming language from code content."""
    scores = {lang: 0 for lang in _LANG_HINTS}
    for line in code.split("\n")[:50]:
        for lang, patterns in _LANG_HINTS.items():
            for pat in patterns:
                if pat.search(line):
                    scores[lang] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "python"

def is_unified_diff(text: str) -> bool:
    """Check whether the input looks like a unified diff."""
    lines = text.strip().split("\n")
    for line in lines[:10]:
        if line.startswith("diff --git") or line.startswith("---") or line.startswith("+++"):
            return True
        if HUNK_HEADER_RE.match(line):
            return True
    return False

def wrap_raw_code(code: str, filename: Optional[str] = None) -> str:
    """Wrap raw code into a synthetic unified diff."""
    lang = _guess_language(code)
    ext = _LANG_EXT.get(lang, ".py")
    fname = filename or f"input{ext}"

    lines = code.split("\n")
    # Strip trailing empty line to avoid off-by-one in line count
    if lines and lines[-1] == "":
        lines = lines[:-1]
    count = len(lines)

    diff_lines = [
        f"diff --git a/{fname} b/{fname}",
        "new file mode 100644",
        "--- /dev/null",
        f"+++ b/{fname}",
        f"@@ -0,0 +1,{count} @@",
    ]
    for line in lines:
        diff_lines.append(f"+{line}")

    return "\n".join(diff_lines)
