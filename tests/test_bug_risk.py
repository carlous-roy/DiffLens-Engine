"""Tests for the bug risk rules."""

from app.analysis.bug_risk import detect_bug_risks
from app.analysis.diff_parser import SourceView


def _rules(source: str, language: str = "python", filename: str = "test.py") -> set[str]:
    return {f.rule_id for f in detect_bug_risks(source, filename, language)}


class TestPythonBugRisks:
    def test_bare_except(self):
        source = "try:\n    pass\nexcept:\n    pass\n"
        assert "PY001" in _rules(source)

    def test_silent_except(self):
        source = "try:\n    pass\nexcept ValueError: pass\n"
        assert "PY002" in _rules(source)

    def test_mutable_default(self):
        assert "PY003" in _rules("def func(data=[]):\n    return data\n")

    def test_none_equality(self):
        assert "PY005" in _rules("if x == None:\n    pass\n")

    def test_eval_usage(self):
        findings = detect_bug_risks("result = eval(user_input)\n", "test.py", "python")
        assert [f.rule_id for f in findings] == ["PY008"]
        assert findings[0].line_number == 1
        assert findings[0].matched_text == "eval("

    def test_exec_usage(self):
        assert "PY008" in _rules("exec(code)\n")

    def test_literal_eval_is_not_eval(self):
        assert "PY008" not in _rules("value = ast.literal_eval(text)\n")

    def test_method_named_eval_is_not_eval(self):
        assert "PY008" not in _rules("frame.eval('a > 1')\n")

    def test_wildcard_import(self):
        assert "PY009" in _rules("from os import *\n")

    def test_global(self):
        assert "PY006" in _rules("def f():\n    global STATE\n    STATE = 1\n")

    def test_todo_comment(self):
        findings = detect_bug_risks("x = 1  # TODO: fix this\n", "test.py", "python")
        assert [f.rule_id for f in findings] == ["PY007"]
        assert findings[0].line_number == 1

    def test_clean_code_no_findings(self):
        assert _rules("def add(a, b):\n    return a + b\n") == set()


class TestRulesRespectSyntax:
    """Rules never match inside comments or string literals."""

    def test_eval_in_comment_not_flagged(self):
        assert "PY008" not in _rules("x = 1  # never call eval(x) here\n")

    def test_eval_in_string_not_flagged(self):
        assert "PY008" not in _rules('message = "eval(x) is unsafe"\n')

    def test_eval_in_docstring_not_flagged(self):
        source = (
            'def f():\n    """Do not use eval(x) or exec(y).\n\n    except:\n    """\n'
            "    return 1\n"
        )
        assert _rules(source) == set()

    def test_eval_inside_fstring_interpolation_is_code(self):
        # The `{...}` part of an f-string is executed, so it is checked.
        assert "PY008" in _rules('print(f"{eval(x)} done")\n')

    def test_none_comparison_in_string_not_flagged(self):
        assert "PY005" not in _rules('doc = "x == None is wrong"\n')

    def test_todo_in_string_not_flagged(self):
        assert "PY007" not in _rules('label = "# TODO"\n')

    def test_multiline_string_masked_on_every_line(self):
        source = 'text = """\neval(a)\nexec(b)\n"""\nvalue = 1\n'
        assert _rules(source) == set()

    def test_java_rules_in_comments_not_flagged(self):
        source = (
            "class A {\n"
            "  // if (name.equals(null)) System.out.println(x);\n"
            '  /* new Thread(); name == "admin" */\n'
            "}\n"
        )
        assert _rules(source, "java", "A.java") == set()

    def test_java_rules_in_string_not_flagged(self):
        source = 'class A {\n  String s = ".equals(null) System.out.println";\n}\n'
        assert _rules(source, "java", "A.java") == set()

    def test_java_string_comparison_still_detected(self):
        # The string delimiters stay in the masked code, so `==` against a
        # literal is still visible even though the literal's text is not.
        source = 'class A {\n  boolean f(String n) { return n == "admin"; }\n}\n'
        assert "JV003" in _rules(source, "java", "A.java")

    def test_java_todo_in_block_comment(self):
        source = "class A {\n  /*\n   * TODO: later\n   */\n}\n"
        findings = detect_bug_risks(source, "A.java", "java")
        assert [f.rule_id for f in findings] == ["JV006"]
        assert findings[0].line_number == 3


class TestJavaBugRisks:
    def test_equals_null(self):
        assert "JV001" in _rules("if (x.equals(null)) {}\n", "java", "T.java")

    def test_string_comparison(self):
        assert "JV003" in _rules('if (name == "hello") {}\n', "java", "T.java")

    def test_empty_catch(self):
        assert "JV002" in _rules("try {} catch (Exception e) {}\n", "java", "T.java")

    def test_system_out(self):
        assert "JV004" in _rules("System.out.println(x);\n", "java", "T.java")


class TestLineMapping:
    def test_findings_use_file_line_numbers_from_view(self):
        text = "x = 1\nresult = eval(data)\ny = 2\nz = exec(code)\n"
        view = SourceView(
            text=text, line_numbers=[40, 41, 42, 43], changed=[False, True, False, True]
        )
        findings = detect_bug_risks(text, "app.py", "python", view)
        assert [(f.rule_id, f.line_number) for f in findings] == [("PY008", 41), ("PY008", 43)]

    def test_unchanged_lines_are_not_reported(self):
        text = "result = eval(data)\n"
        view = SourceView(text=text, line_numbers=[10], changed=[False])
        assert detect_bug_risks(text, "app.py", "python", view) == []


def test_unsupported_language():
    assert detect_bug_risks("fn main() {}", "test.rs", "rust") == []
