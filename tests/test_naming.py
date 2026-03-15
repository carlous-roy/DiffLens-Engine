"""Tests for naming convention validators."""
from app.analysis.naming import check_python_naming, check_java_naming

class TestPythonNaming:
    def test_bad_class_name(self):
        code = "class myClass:\n    pass\n"
        findings = check_python_naming(code, "test.py")
        assert len(findings) == 1
        assert findings[0].kind == "class"
        assert "PascalCase" in findings[0].message

    def test_good_class_name(self):
        code = "class MyClass:\n    pass\n"
        findings = check_python_naming(code, "test.py")
        assert len(findings) == 0

    def test_bad_function_name(self):
        code = "def ProcessData(x):\n    return x\n"
        findings = check_python_naming(code, "test.py")
        assert len(findings) == 1
        assert findings[0].kind == "function"
        assert "snake_case" in findings[0].message

    def test_good_function_name(self):
        code = "def process_data(x):\n    return x\n"
        findings = check_python_naming(code, "test.py")
        assert len(findings) == 0

    def test_dunder_allowed(self):
        code = "def __init__(self):\n    pass\n"
        findings = check_python_naming(code, "test.py")
        assert len(findings) == 0

    def test_private_method_allowed(self):
        code = "def _helper(x):\n    return x\n"
        findings = check_python_naming(code, "test.py")
        assert len(findings) == 0

class TestJavaNaming:
    def test_bad_method_name(self):
        code = "public void Process_Data(String x) {\n}\n"
        findings = check_java_naming(code, "Test.java")
        assert len(findings) >= 1
        method_findings = [f for f in findings if f.kind == "method"]
        assert len(method_findings) == 1
        assert "camelCase" in method_findings[0].message

    def test_good_method_name(self):
        code = "public void processData(String x) {\n}\n"
        findings = check_java_naming(code, "Test.java")
        method_findings = [f for f in findings if f.kind == "method"]
        assert len(method_findings) == 0

    def test_bad_constant(self):
        code = "static final String appName = \"test\";\n"
        findings = check_java_naming(code, "Test.java")
        const_findings = [f for f in findings if f.kind == "constant"]
        assert len(const_findings) == 1
        assert "SCREAMING_SNAKE_CASE" in const_findings[0].message

    def test_good_constant(self):
        code = 'static final String APP_NAME = "test";\n'
        findings = check_java_naming(code, "Test.java")
        const_findings = [f for f in findings if f.kind == "constant"]
        assert len(const_findings) == 0
