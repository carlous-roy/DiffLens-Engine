"""Tests for the unified diff parser."""

from app.analysis.diff_parser import _guess_language, is_unified_diff, parse_diff, wrap_raw_code


def test_parse_new_file():
    diff = """diff --git a/hello.py b/hello.py
new file mode 100644
--- /dev/null
+++ b/hello.py
@@ -0,0 +1,3 @@
+def hello():
+    print("hello")
+    return True
"""
    files = parse_diff(diff)
    assert len(files) == 1
    assert files[0].is_new_file is True
    assert files[0].old_path is None
    assert files[0].new_path == "hello.py"
    assert files[0].path == "hello.py"
    assert files[0].language == "python"
    added = files[0].hunks[0].added_lines
    removed = files[0].hunks[0].removed_lines
    assert len(added) == 3
    assert len(removed) == 0


def test_parse_deleted_file():
    diff = """diff --git a/old.py b/old.py
deleted file mode 100644
--- a/old.py
+++ /dev/null
@@ -1,2 +0,0 @@
-def old():
-    pass
"""
    files = parse_diff(diff)
    assert len(files) == 1
    assert files[0].is_deleted_file is True
    assert files[0].old_path == "old.py"
    assert files[0].new_path is None
    assert len(files[0].hunks[0].removed_lines) == 2
    assert len(files[0].hunks[0].added_lines) == 0


def test_language_detection():
    diff = """diff --git a/test.js b/test.js
--- /dev/null
+++ b/test.js
@@ -0,0 +1 @@
+console.log("hello");
"""
    files = parse_diff(diff)
    assert len(files) == 1
    assert files[0].path == "test.js"
    assert files[0].language == "javascript"
    assert files[0].all_added_content == 'console.log("hello");'


def test_is_unified_diff_true():
    diff = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-old\n+new"
    assert is_unified_diff(diff) is True


def test_is_unified_diff_false_raw_python():
    code = "def hello():\n    print('hello')\n    return True"
    assert is_unified_diff(code) is False


def test_is_unified_diff_false_raw_java():
    code = "public class Main {\n    public static void main(String[] args) {}\n}"
    assert is_unified_diff(code) is False


def test_is_unified_diff_false_random_text():
    assert is_unified_diff("Printtt('Roy')") is False


def test_guess_language_python():
    code = "import os\ndef hello():\n    print('hi')"
    assert _guess_language(code) == "python"


def test_guess_language_java():
    code = (
        "public class Main {\n"
        "    public static void main(String[] args) {\n"
        "        System.out.println('hi');\n"
        "    }\n"
        "}"
    )
    assert _guess_language(code) == "java"


def test_guess_language_defaults_to_python():
    code = "x = 42\ny = x + 1"
    assert _guess_language(code) == "python"


def test_wrap_raw_code_produces_valid_diff():
    code = "def hello():\n    return True"
    wrapped = wrap_raw_code(code)
    assert is_unified_diff(wrapped) is True
    files = parse_diff(wrapped)
    assert len(files) == 1
    assert files[0].is_new_file is True
    assert files[0].language == "python"
    assert "def hello():" in files[0].all_added_content


def test_wrap_raw_code_custom_filename():
    code = "console.log('hi')"
    wrapped = wrap_raw_code(code, filename="app.js")
    files = parse_diff(wrapped)
    assert files[0].path == "app.js"
    assert files[0].language == "javascript"


def test_wrap_raw_code_line_count():
    code = "line1\nline2\nline3"
    wrapped = wrap_raw_code(code)
    files = parse_diff(wrapped)
    assert len(files[0].hunks[0].added_lines) == 3


def test_pipeline_handles_raw_code():
    """Integration test: raw code goes through the full pipeline."""
    from app.analysis.pipeline import run_analysis

    code = "from os import *\ndef ProcessData(data, cache={}):\n    eval(data)\n    pass"
    result = run_analysis(code, enable_ml=False)
    # Should detect findings — not return 0
    assert result.files_analyzed == 1
    assert result.total_findings > 0


def test_pipeline_still_handles_diffs():
    """Ensure normal diffs still work after adding auto-detect."""
    from app.analysis.pipeline import run_analysis

    diff = """diff --git a/f.py b/f.py
new file mode 100644
--- /dev/null
+++ b/f.py
@@ -0,0 +1,3 @@
+from os import *
+def ProcessData():
+    eval("x")
"""
    result = run_analysis(diff, enable_ml=False)
    assert result.files_analyzed == 1
    assert result.total_findings > 0


MODIFIED_FILE_DIFF = "\n".join(
    [
        "diff --git a/pkg/service.py b/pkg/service.py",
        "--- a/pkg/service.py",
        "+++ b/pkg/service.py",
        "@@ -95,7 +100,12 @@ class Service:",
        "     def existing(self):",
        "         return 1",
        " ",  # blank context line: a single space in a unified diff
        "+    def route(self, x):",
        "+        if x:",
        "+            return eval(x)  # eval(y) in a comment",
        '+        return "eval(z) in a string"',
        "+",
        "     def other(self):",
        "         return 2",
        "@@ -140,4 +150,4 @@ class Service:",
        "     def last(self):",
        "-        return old_value",
        "+        return exec(new_value)",
        "",
    ]
)


def test_post_image_view_numbers_lines_by_new_file():
    files = parse_diff(MODIFIED_FILE_DIFF)
    view = files[0].post_image()
    assert view.text.split("\n")[3] == "    def route(self, x):"
    assert view.line_numbers[:9] == [100, 101, 102, 103, 104, 105, 106, 107, 108]
    assert view.changed[:9] == [False, False, False, True, True, True, True, True, False]
    # Second hunk: context line 150, added line 151 (the removed line is gone).
    assert view.line_numbers[-2:] == [150, 151]
    assert view.changed[-2:] == [False, True]
    assert view.map_line(4) == 103
    assert view.is_changed(4) is True
    assert view.has_changes is True


def test_pre_image_view_numbers_lines_by_old_file():
    files = parse_diff(MODIFIED_FILE_DIFF)
    view = files[0].pre_image()
    assert view.line_numbers[-2:] == [140, 141]
    assert view.changed[-2:] == [False, True]
    assert view.text.split("\n")[-1] == "        return old_value"


def test_source_view_from_text_is_identity():
    from app.analysis.diff_parser import SourceView

    view = SourceView.from_text("a\nb\nc")
    assert view.line_numbers == [1, 2, 3]
    assert view.changed == [True, True, True]
    assert view.map_line(2) == 2
    assert view.map_line(99) == 99  # out of range: returned unchanged
    assert view.is_changed(99) is False
