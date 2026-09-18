"""Tree-sitter parsing shared by the analyzers.

Everything that needs the syntax tree goes through this module: parser
construction, an iterative tree walk (no recursion, so deeply nested input
cannot exhaust the interpreter stack), and a "code mask" that blanks out
comments and string contents so that text rules only ever match code.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

try:
    import tree_sitter_java as tsjava
    import tree_sitter_python as tspython
    from tree_sitter import Language, Node, Parser, Tree

    LANGUAGES: dict[str, Language] = {
        "python": Language(tspython.language()),
        "java": Language(tsjava.language()),
    }
    TREE_SITTER_AVAILABLE = True
except Exception:  # pragma: no cover - exercised only when the wheels are missing
    LANGUAGES = {}
    TREE_SITTER_AVAILABLE = False
    Node = Parser = Tree = object  # type: ignore[misc,assignment]

SUPPORTED_LANGUAGES = frozenset({"python", "java"})

# Node types whose whole extent is a comment.
COMMENT_NODE_TYPES: dict[str, frozenset[str]] = {
    "python": frozenset({"comment"}),
    "java": frozenset({"line_comment", "block_comment"}),
}

# Node types whose whole extent is string *content* (delimiters excluded).
# Python f-string interpolations are siblings of `string_content`, so the
# code inside `{...}` stays visible to the rules.
STRING_CONTENT_NODE_TYPES: dict[str, frozenset[str]] = {
    "python": frozenset({"string_content"}),
    "java": frozenset({"string_fragment", "multiline_string_fragment", "escape_sequence"}),
}

# Leaf string tokens that carry their own delimiters: blank everything
# between the first and last byte.
DELIMITED_LEAF_NODE_TYPES: dict[str, frozenset[str]] = {
    "python": frozenset(),
    "java": frozenset({"character_literal"}),
}


def parser_for(language: str) -> Parser:
    """Return a parser for `language` ("python" or "java")."""
    if language not in LANGUAGES:
        raise ValueError(f"Unsupported language: {language}")
    return Parser(LANGUAGES[language])


def parse(source: str | bytes, language: str) -> Tree:
    """Parse source text into a Tree-sitter tree."""
    data = source if isinstance(source, bytes) else source.encode("utf-8")
    return parser_for(language).parse(data)


def iter_nodes(root: Node) -> Iterator[Node]:
    """Depth-first, pre-order traversal without recursion."""
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        # Push in reverse so children are visited in source order.
        stack.extend(reversed(node.children))


def node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


@dataclass
class MaskedSource:
    """A view of the source in which comments and string contents are blanked.

    `code` has the same line structure as the original, so a match on line N
    of `code` is on line N of the source. (Columns inside a masked region can
    shift for multi-byte characters, which is why the rules work per line.)
    `comments` lists every comment as (1-based line, text), one entry per
    line for multi-line comments, for rules that look *inside* comments.
    """

    code: str
    comments: list[tuple[int, str]] = field(default_factory=list)

    @property
    def code_lines(self) -> list[str]:
        return self.code.split("\n")


def mask_comments_and_strings(source: str, language: str) -> MaskedSource:
    """Blank comments and string contents using the syntax tree.

    Every masked byte becomes a space except newlines, which are kept so
    line numbers survive. String delimiters are kept so rules that reason
    about string *usage* (`x == "literal"`) still see a literal there.
    """
    if language not in LANGUAGES:
        return MaskedSource(code=source)

    data = source.encode("utf-8")
    tree = parse(data, language)
    buf = bytearray(data)
    comments: list[tuple[int, str]] = []

    comment_types = COMMENT_NODE_TYPES[language]
    string_types = STRING_CONTENT_NODE_TYPES[language]
    leaf_types = DELIMITED_LEAF_NODE_TYPES[language]

    def blank(start: int, end: int) -> None:
        for i in range(start, end):
            if buf[i] != 0x0A:  # keep "\n"
                buf[i] = 0x20

    for node in iter_nodes(tree.root_node):
        ntype = node.type
        if ntype in comment_types:
            text = node_text(node, data)
            for offset, line in enumerate(text.split("\n")):
                comments.append((node.start_point[0] + 1 + offset, line))
            blank(node.start_byte, node.end_byte)
        elif ntype in string_types:
            blank(node.start_byte, node.end_byte)
        elif ntype in leaf_types and node.end_byte - node.start_byte >= 2:
            blank(node.start_byte + 1, node.end_byte - 1)

    # Masked regions are now pure ASCII and unmasked regions are untouched
    # UTF-8, so the buffer decodes cleanly; "replace" is a safety net only.
    return MaskedSource(code=buf.decode("utf-8", errors="replace"), comments=comments)
