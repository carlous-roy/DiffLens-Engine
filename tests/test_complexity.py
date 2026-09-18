"""Tests for the complexity analyzer."""

import pytest

from app.analysis.complexity import analyze_complexity
from app.analysis.diff_parser import SourceView
from app.analysis.syntax import TREE_SITTER_AVAILABLE

pytestmark = pytest.mark.skipif(not TREE_SITTER_AVAILABLE, reason="tree-sitter not installed")


def _cyclomatic(findings):
    return [f for f in findings if f.metric == "cyclomatic_complexity"]


def _nesting(findings):
    return [f for f in findings if f.metric == "nesting_depth"]


class TestPythonComplexity:
    def test_simple_function(self):
        code = "def add(a, b):\n    return a + b\n"
        findings = analyze_complexity(code, "test.py", "python")
        assert len(findings) == 1
        assert findings[0].function_name == "add"
        assert findings[0].complexity == 1
        assert findings[0].nesting_depth == 0
        assert findings[0].severity == "info"

    def test_each_decision_point_counts_once(self):
        code = """
def process(data):
    if data:
        for item in data:
            if item > 0 and item < 10:
                return item
            elif item == 0:
                continue
    return None
"""
        findings = _cyclomatic(analyze_complexity(code, "test.py", "python"))
        assert len(findings) == 1
        # base 1 + if + for + if + `and` + elif = 6
        assert findings[0].complexity == 6
        assert findings[0].nesting_depth == 3
        assert findings[0].severity == "warning"

    def test_match_statement_cases_count(self):
        code = (
            "def kind(x):\n"
            "    match x:\n"
            "        case 1:\n"
            "            return 'one'\n"
            "        case 2:\n"
            "            return 'two'\n"
            "    return 'other'\n"
        )
        findings = _cyclomatic(analyze_complexity(code, "test.py", "python"))
        assert findings[0].complexity == 3

    def test_nested_function_is_measured_separately(self):
        code = (
            "def outer(x):\n"
            "    if x:\n"
            "        pass\n"
            "    def inner(y):\n"
            "        if y:\n"
            "            pass\n"
            "        if y > 1:\n"
            "            pass\n"
            "    return inner\n"
        )
        findings = {
            f.function_name: f for f in _cyclomatic(analyze_complexity(code, "t.py", "python"))
        }
        assert findings["outer"].complexity == 2
        assert findings["inner"].complexity == 3

    def test_severity_thresholds(self):
        branches = "\n".join(f"    if x == {i}:\n        pass" for i in range(12))
        code = f"def many(x):\n{branches}\n"
        findings = _cyclomatic(analyze_complexity(code, "test.py", "python"))
        assert findings[0].complexity == 13
        assert findings[0].severity == "error"
        assert findings[0].suggestion is not None

    def test_deep_nesting_reported(self):
        code = (
            "def f(x):\n"
            + "".join("    " * (i + 1) + "if x:\n" for i in range(5))
            + "    " * 6
            + "return 1\n"
        )
        findings = analyze_complexity(code, "test.py", "python")
        nesting = _nesting(findings)
        assert len(nesting) == 1
        assert nesting[0].nesting_depth == 5
        assert nesting[0].severity == "warning"
        assert "nesting depth of 5" in nesting[0].message

        code6 = (
            "def f(x):\n"
            + "".join("    " * (i + 1) + "if x:\n" for i in range(6))
            + "    " * 7
            + "return 1\n"
        )
        assert _nesting(analyze_complexity(code6, "test.py", "python"))[0].severity == "error"

    def test_shallow_nesting_not_reported(self):
        code = (
            "def f(x):\n    if x:\n        for i in x:\n            if i:\n                pass\n"
        )
        findings = analyze_complexity(code, "test.py", "python")
        assert _nesting(findings) == []
        assert _cyclomatic(findings)[0].nesting_depth == 3

    def test_deeply_nested_expression_does_not_recurse(self):
        code = "def f():\n    return " + "(" * 3000 + "1" + ")" * 3000 + "\n"
        findings = analyze_complexity(code, "test.py", "python")
        assert findings[0].function_name == "f"


class TestJavaComplexity:
    def test_simple_method(self):
        code = """
class Foo {
    public int add(int a, int b) {
        return a + b;
    }
}
"""
        findings = analyze_complexity(code, "Foo.java", "java")
        assert len(findings) == 1
        assert findings[0].function_name == "add"
        assert findings[0].complexity == 1
        assert findings[0].severity == "info"

    def test_short_circuit_operators_and_cases_count(self):
        code = """
class Foo {
    int f(int a, int b) {
        if (a > 0 && b > 0 || a == b) { return 1; }
        switch (a) {
            case 1: return 2;
            case 2: return 3;
            default: return 4;
        }
    }
}
"""
        findings = _cyclomatic(analyze_complexity(code, "Foo.java", "java"))
        # base 1 + if + && + || + three case groups = 7
        assert findings[0].complexity == 7

    def test_else_if_chain_is_one_nesting_level(self):
        code = """
class Foo {
    int f(int a) {
        if (a == 1) { return 1; }
        else if (a == 2) { return 2; }
        else if (a == 3) { return 3; }
        return 0;
    }
}
"""
        findings = _cyclomatic(analyze_complexity(code, "Foo.java", "java"))
        assert findings[0].complexity == 4
        assert findings[0].nesting_depth == 1

    def test_constructor_measured(self):
        code = "class Foo {\n    Foo(int a) {\n        if (a > 0) { }\n    }\n}\n"
        findings = _cyclomatic(analyze_complexity(code, "Foo.java", "java"))
        assert findings[0].function_name == "Foo"
        assert findings[0].complexity == 2


class TestLineMapping:
    def test_function_line_mapped_through_view(self):
        text = (
            "class S:\n    def old(self):\n        pass\n\n"
            "    def route(self, x):\n        if x:\n            return x\n"
        )
        view = SourceView(
            text=text,
            line_numbers=[100, 101, 102, 103, 104, 105, 106],
            changed=[False, False, False, True, True, True, True],
        )
        findings = analyze_complexity(text, "s.py", "python", view)
        assert [(f.function_name, f.line_number) for f in findings] == [("route", 104)]

    def test_unchanged_definition_not_reported(self):
        text = "def old(self):\n    pass\n"
        view = SourceView(text=text, line_numbers=[7, 8], changed=[False, True])
        assert analyze_complexity(text, "s.py", "python", view) == []
