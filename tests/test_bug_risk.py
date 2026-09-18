"""Tests for the bug risk detector."""

from app.analysis.bug_risk import detect_bug_risks


class TestPythonBugRisks:
    def test_bare_except(self):
        lines = [(10, "except:")]
        findings = detect_bug_risks(lines, "test.py", "python")
        assert any(f.rule_id == "PY001" for f in findings)

    def test_silent_except(self):
        lines = [(10, "except ValueError: pass")]
        findings = detect_bug_risks(lines, "test.py", "python")
        assert any(f.rule_id == "PY002" for f in findings)

    def test_mutable_default(self):
        lines = [(10, "def func(data=[]):")]
        findings = detect_bug_risks(lines, "test.py", "python")
        assert any(f.rule_id == "PY003" for f in findings)

    def test_none_equality(self):
        lines = [(10, "if x == None:")]
        findings = detect_bug_risks(lines, "test.py", "python")
        assert any(f.rule_id == "PY005" for f in findings)

    def test_eval_usage(self):
        lines = [(10, "result = eval(user_input)")]
        findings = detect_bug_risks(lines, "test.py", "python")
        assert any(f.rule_id == "PY008" for f in findings)

    def test_wildcard_import(self):
        lines = [(1, "from os import *")]
        findings = detect_bug_risks(lines, "test.py", "python")
        assert any(f.rule_id == "PY009" for f in findings)

    def test_todo_comment(self):
        lines = [(10, "# TODO: fix this")]
        findings = detect_bug_risks(lines, "test.py", "python")
        assert any(f.rule_id == "PY007" for f in findings)

    def test_clean_code_no_findings(self):
        lines = [
            (1, "def add(a, b):"),
            (2, "    return a + b"),
        ]
        findings = detect_bug_risks(lines, "test.py", "python")
        assert len(findings) == 0


class TestJavaBugRisks:
    def test_equals_null(self):
        lines = [(10, "if (x.equals(null))")]
        findings = detect_bug_risks(lines, "Test.java", "java")
        assert any(f.rule_id == "JV001" for f in findings)

    def test_string_comparison(self):
        lines = [(10, 'if (name == "hello")')]
        findings = detect_bug_risks(lines, "Test.java", "java")
        assert any(f.rule_id == "JV003" for f in findings)

    def test_empty_catch(self):
        lines = [(10, "catch (Exception e) {}")]
        findings = detect_bug_risks(lines, "Test.java", "java")
        assert any(f.rule_id == "JV002" for f in findings)

    def test_system_out(self):
        lines = [(10, "System.out.println(x);")]
        findings = detect_bug_risks(lines, "Test.java", "java")
        assert any(f.rule_id == "JV004" for f in findings)


def test_unsupported_language():
    lines = [(1, "fn main() {}")]
    findings = detect_bug_risks(lines, "test.rs", "rust")
    assert findings == []
