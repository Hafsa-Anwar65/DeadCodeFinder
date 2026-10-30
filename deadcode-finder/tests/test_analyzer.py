import textwrap

from deadcode_finder import analyze_source
from deadcode_finder.analyzer import analyze_paths


def kinds(src, **kw):
    return [(f.kind, f.name) for f in analyze_source(textwrap.dedent(src), **kw)]


def test_unused_imports():
    src = """
    import os, sys
    from typing import Optional, List
    print(sys, Optional)
    """
    found = kinds(src)
    assert ("unused-import", "os") in found
    assert ("unused-import", "List") in found
    assert ("unused-import", "sys") not in found


def test_import_used_in_string_annotation():
    assert kinds("""
    from typing import Optional
    def f(x: "Optional[int]"):
        return x
    f(1)
    """) == []


def test_reexport_idioms_are_ignored():
    assert kinds("""
    from pkg import a as a
    from pkg import b
    __all__ = ["b"]
    """) == []


def test_future_imports_ignored():
    assert kinds("from __future__ import annotations\n") == []


def test_init_file_imports_skipped(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("from .core import thing\n")
    (pkg / "core.py").write_text("def thing():\n    return 1\n")
    findings, _ = analyze_paths([str(tmp_path)], min_confidence=0)
    assert findings == []


def test_unused_local_variable():
    found = kinds("""
    def f():
        a = 1
        b = 2
        _ignored = 3
        return b
    f()
    """)
    assert found == [("unused-variable", "a")]


def test_variable_used_in_nested_function():
    assert kinds("""
    def outer():
        x = 1
        def inner():
            return x
        return inner
    outer()
    """) == []


def test_locals_call_disables_variable_check():
    assert kinds("""
    def f():
        name = "x"
        return locals()
    f()
    """) == []


def test_unreachable_code():
    found = analyze_source(textwrap.dedent("""
    def f():
        return 1
        print("never")
        x = 2
    f()
    """))
    unreachable = [f for f in found if f.kind == "unreachable-code"]
    assert len(unreachable) == 1
    assert unreachable[0].line == 4 and unreachable[0].end_line == 5


def test_unreachable_in_except_reported_once():
    found = kinds("""
    try:
        pass
    except Exception:
        raise
        print("never")
    """)
    assert found.count(("unreachable-code", "after-raise")) == 1


def test_unused_function_and_class_across_files(tmp_path):
    (tmp_path / "a.py").write_text("def used():\n    pass\n\ndef dead():\n    pass\n\nclass Ghost:\n    pass\n")
    (tmp_path / "b.py").write_text("from a import used\nused()\n")
    findings, _ = analyze_paths([str(tmp_path)])
    names = {(f.kind, f.name) for f in findings}
    assert ("unused-function", "dead") in names
    assert ("unused-class", "Ghost") in names
    assert ("unused-function", "used") not in names


def test_decorated_functions_get_low_confidence():
    src = """
    @app.route("/")
    def index():
        return "hi"
    """
    assert kinds(src, min_confidence=60) == []
    assert ("unused-function", "index") in kinds(src, min_confidence=0)


def test_private_unused_function_higher_confidence():
    f = analyze_source("def _helper():\n    pass\n")[0]
    assert f.confidence == 80


def test_dunder_and_implicit_methods_skipped():
    assert kinds("""
    class A:
        def __init__(self):
            pass
        def setUp(self):
            pass
    A()
    """) == []


def test_getattr_string_counts_as_usage():
    assert kinds("""
    def handler():
        pass
    getattr(module, "handler")
    """) == []


def test_ignore_comment():
    assert kinds("""
    import os  # deadcode: ignore
    def keep():  # dcf: ignore
        pass
    """) == []


def test_ignore_names_glob():
    assert kinds("def plugin_load():\n    pass\n", ignore_names=["plugin_*"]) == []


def test_test_functions_skipped(tmp_path):
    (tmp_path / "test_x.py").write_text("def test_something():\n    assert True\n")
    findings, _ = analyze_paths([str(tmp_path)])
    assert findings == []


def test_syntax_errors_reported_not_raised(tmp_path):
    (tmp_path / "bad.py").write_text("def (:\n")
    findings, errors = analyze_paths([str(tmp_path)])
    assert findings == [] and len(errors) == 1


def test_venv_and_excludes_skipped(tmp_path):
    for d in ("venv", "migrations"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "m.py").write_text("import os\n")
    findings, _ = analyze_paths([str(tmp_path)], exclude=["migrations"])
    assert findings == []


def test_noqa_import_respected():
    assert kinds("import socket  # noqa: F401\nimport ssl  # noqa\n") == []


def test_project_reexport_not_flagged(tmp_path):
    (tmp_path / "compat.py").write_text("try:\n    import simplejson as json\nexcept ImportError:\n    import json\n")
    (tmp_path / "models.py").write_text("from .compat import json\nprint(json)\n")
    (tmp_path / "other.py").write_text("from typing import List\n")
    findings, _ = analyze_paths([str(tmp_path)])
    assert [(f.path.split("/")[-1], f.name) for f in findings] == [("other.py", "List")]
