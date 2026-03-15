"""Tests for the complexity analyzer."""
from app.analysis.complexity import analyze_complexity, TREE_SITTER_AVAILABLE
import pytest

@pytest.mark.skipif(not TREE_SITTER_AVAILABLE, reason="tree-sitter not installed")
class TestPythonComplexity:
    def test_simple_function(self):
        code = "def add(a, b):\n    return a + b\n"
        findings = analyze_complexity(code, "test.py", "python")
        assert len(findings) == 1
        assert findings[0].function_name == "add"
        assert findings[0].complexity == 1
        assert findings[0].severity == "info"

    def test_moderate_complexity(self):
        code = """
def process(data):
    if data:
        for item in data:
            if item > 0:
                return item
            elif item == 0:
                continue
    return None
"""findings = analyze_complexity(code, "test.py", "python")"""
        findings = analyze_complexity(code, "test.py", "python")
        assert len(findings) == 2

@pytest.mark.skipif(not TREE_SITTER_AVAILABLE, reason="tree-sitter not installed")
class TestJavaComplexity:
    def test_simple_method(self):
        code = """
class Foo {
    public int add(int a, int b) {
        return a + b;
    }
}
"""findings = analyze_complexity(code, "Foo.java", "java")"""