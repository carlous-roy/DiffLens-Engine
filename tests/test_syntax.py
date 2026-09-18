"""Tests for the shared Tree-sitter helpers."""

from app.analysis.syntax import iter_nodes, mask_comments_and_strings, parse


class TestMask:
    def test_python_comment_and_string_contents_blanked(self):
        source = 'x = eval("a")  # eval(b)\ns = "eval(c)"\n'
        masked = mask_comments_and_strings(source, "python")
        assert masked.code == 'x = eval(" ")           \ns = "       "\n'
        assert masked.comments == [(1, "# eval(b)")]

    def test_line_structure_preserved_for_multiline_strings(self):
        source = 'doc = """\nline one\nline two\n"""\ny = 1\n'
        masked = mask_comments_and_strings(source, "python")
        assert masked.code.count("\n") == source.count("\n")
        assert masked.code_lines[1].strip() == ""
        assert masked.code_lines[4] == "y = 1"

    def test_fstring_interpolation_kept(self):
        masked = mask_comments_and_strings('f"{eval(x)} ok"\n', "python")
        assert "eval(x)" in masked.code
        assert " ok" not in masked.code

    def test_java_comments_strings_and_chars(self):
        source = "int a = 1; // note\n/* multi\n line */\nString s = \"hi\"; char c = 'x';\n"
        masked = mask_comments_and_strings(source, "java")
        assert masked.code_lines[0] == "int a = 1;        "
        assert masked.code_lines[1].strip() == ""
        assert masked.code_lines[2].strip() == ""
        assert masked.code_lines[3] == "String s = \"  \"; char c = ' ';"
        assert masked.comments == [(1, "// note"), (2, "/* multi"), (3, " line */")]

    def test_non_ascii_string_contents(self):
        masked = mask_comments_and_strings('s = "héllo wörld"\nt = 2\n', "python")
        assert masked.code_lines[1] == "t = 2"
        assert masked.code_lines[0].startswith('s = "')

    def test_unsupported_language_returns_source_unchanged(self):
        masked = mask_comments_and_strings("let x = 1; // c", "javascript")
        assert masked.code == "let x = 1; // c"
        assert masked.comments == []


class TestWalk:
    def test_iter_nodes_is_preorder_and_iterative(self):
        tree = parse("def f():\n    return 1\n", "python")
        types = [n.type for n in iter_nodes(tree.root_node)]
        assert types[:3] == ["module", "function_definition", "def"]

    def test_iter_nodes_handles_deep_trees(self):
        tree = parse("x = " + "(" * 5000 + "1" + ")" * 5000, "python")
        assert sum(1 for _ in iter_nodes(tree.root_node)) > 5000
