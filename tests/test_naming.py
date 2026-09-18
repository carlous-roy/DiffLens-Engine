"""Tests for naming convention validators."""

from app.analysis.diff_parser import SourceView
from app.analysis.naming import check_java_naming, check_python_naming


def _by_kind(findings, kind):
    return [f for f in findings if f.kind == kind]


class TestPythonNaming:
    def test_bad_class_name(self):
        findings = check_python_naming("class myClass:\n    pass\n", "test.py")
        assert len(findings) == 1
        assert findings[0].kind == "class"
        assert "PascalCase" in findings[0].message
        assert findings[0].suggestion == "Rename to 'MyClass'."

    def test_good_class_name(self):
        assert check_python_naming("class MyClass:\n    pass\n", "test.py") == []

    def test_bad_function_name(self):
        findings = check_python_naming("def ProcessData(x):\n    return x\n", "test.py")
        assert len(findings) == 1
        assert findings[0].kind == "function"
        assert "snake_case" in findings[0].message
        assert findings[0].suggestion == "Rename to 'process_data'."

    def test_good_function_name(self):
        assert check_python_naming("def process_data(x):\n    return x\n", "test.py") == []

    def test_dunder_allowed(self):
        assert check_python_naming("def __init__(self):\n    pass\n", "test.py") == []

    def test_private_method_allowed(self):
        assert check_python_naming("def _helper(x):\n    return x\n", "test.py") == []

    def test_private_constant_allowed(self):
        assert check_python_naming("_CACHE = {}\nMAX_RETRIES = 3\n", "test.py") == []

    def test_mixed_case_module_constant(self):
        findings = check_python_naming("Max_Retries = 3\n", "test.py")
        assert [(f.kind, f.name) for f in findings] == [("constant", "Max_Retries")]

    def test_camel_case_variable_flagged(self):
        findings = check_python_naming("def f():\n    myVar = 1\n    return myVar\n", "test.py")
        assert [(f.kind, f.name, f.line_number) for f in findings] == [("variable", "myVar", 2)]
        assert findings[0].suggestion == "Rename to 'my_var'."

    def test_pascal_case_alias_allowed(self):
        # Type aliases and re-exported classes follow CapWords under PEP 8.
        assert check_python_naming("Vector = list[float]\nHandler = MyHandler\n", "test.py") == []

    def test_attribute_assignment_not_checked(self):
        assert check_python_naming("obj.someAttr = 1\n", "test.py") == []

    def test_camel_case_parameter_flagged(self):
        findings = check_python_naming("def f(userId, name='x'):\n    pass\n", "test.py")
        assert [(f.kind, f.name) for f in findings] == [("parameter", "userId")]

    def test_definition_inside_string_ignored(self):
        code = 'DOC = """\nclass myClass:\n    def ProcessData(self): pass\n"""\n'
        assert check_python_naming(code, "test.py") == []

    def test_line_numbers_follow_view(self):
        text = "class Ok:\n    def BadName(self):\n        pass\n"
        view = SourceView(text=text, line_numbers=[50, 51, 52], changed=[False, True, True])
        findings = check_python_naming(text, "m.py", view)
        assert [(f.name, f.line_number) for f in findings] == [("BadName", 51)]


class TestJavaNaming:
    def test_bad_method_name(self):
        findings = check_java_naming("public void Process_Data(String x) {\n}\n", "Test.java")
        method_findings = _by_kind(findings, "method")
        assert len(method_findings) == 1
        assert "camelCase" in method_findings[0].message
        assert method_findings[0].suggestion == "Rename to 'processData'."

    def test_pascal_case_method_flagged(self):
        code = "class A {\n    public void ProcessData(String x) {}\n}\n"
        assert [f.name for f in _by_kind(check_java_naming(code, "A.java"), "method")] == [
            "ProcessData"
        ]

    def test_constructor_not_treated_as_method(self):
        code = "class DataHandler {\n    public DataHandler(String x) {}\n}\n"
        assert check_java_naming(code, "DataHandler.java") == []

    def test_good_method_name(self):
        findings = check_java_naming("public void processData(String x) {\n}\n", "Test.java")
        assert _by_kind(findings, "method") == []

    def test_bad_constant(self):
        findings = check_java_naming('static final String appName = "test";\n', "Test.java")
        const_findings = _by_kind(findings, "constant")
        assert len(const_findings) == 1
        assert "SCREAMING_SNAKE_CASE" in const_findings[0].message

    def test_good_constant(self):
        findings = check_java_naming('static final String APP_NAME = "test";\n', "Test.java")
        assert _by_kind(findings, "constant") == []

    def test_bad_class_name(self):
        findings = check_java_naming("public class dataHandler {\n}\n", "Test.java")
        assert [(f.kind, f.name) for f in findings] == [("class", "dataHandler")]

    def test_field_and_local_variable_names(self):
        code = (
            "class A {\n"
            "    private int Retry_Count = 0;\n"
            "    void f() {\n"
            "        int Total_Sum = 1;\n"
            "        final int MAX = 2;\n"
            "        int okName = 3;\n"
            "    }\n"
            "}\n"
        )
        findings = check_java_naming(code, "A.java")
        assert [(f.kind, f.name, f.line_number) for f in findings] == [
            ("field", "Retry_Count", 2),
            ("variable", "Total_Sum", 4),
        ]

    def test_names_inside_comments_ignored(self):
        code = "class A {\n    // public void Process_Data() {}\n    /* class bad_name {} */\n}\n"
        assert check_java_naming(code, "A.java") == []
