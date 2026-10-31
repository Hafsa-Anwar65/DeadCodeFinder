import ast
import textwrap

from deadcode_finder import analyze_source
from deadcode_finder.fixer import fix_source, fix_unused_imports
from deadcode_finder.analyzer import analyze_paths


def fix(src):
    src = textwrap.dedent(src)
    out = fix_source(src, analyze_source(src))
    ast.parse(out)  # result must always be valid Python
    return out


def test_removes_whole_import_line():
    assert fix("import os\nimport sys\nprint(sys)\n") == "import sys\nprint(sys)\n"


def test_removes_only_unused_names():
    out = fix("from typing import Optional, List, Dict  # types\nx: Optional[int] = None\nprint(Dict)\n")
    assert out.splitlines()[0] == "from typing import Optional, Dict  # types"


def test_multiline_import():
    out = fix("""
    from os.path import (
        join,
        exists,
    )
    print(join)
    """)
    assert "from os.path import join" in out and "exists" not in out


def test_keeps_alias():
    out = fix("import numpy as np, os\nprint(np)\n")
    assert out.startswith("import numpy as np\n")


def test_empty_try_block_gets_pass():
    out = fix("""
    try:
        import yaml
        import toml
    except ImportError:
        pass
    """)
    assert "pass" in out.split("except")[0]
    assert "yaml" not in out and "toml" not in out


def test_relative_import_preserved():
    out = fix("from ..pkg import a, b\nprint(a)\n")
    assert out.startswith("from ..pkg import a\n")


def test_semicolon_lines_left_alone():
    src = "import os; import sys\nprint(sys)\n"
    assert fix(src) == src


def test_fix_on_disk_and_dry_run(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("import os\nimport sys\nprint(sys)\n")
    findings, _ = analyze_paths([str(tmp_path)])
    diffs = fix_unused_imports(findings, dry_run=True)
    assert "-import os" in diffs[str(f)]
    assert "import os" in f.read_text()  # dry run didn't write
    fix_unused_imports(findings)
    assert f.read_text() == "import sys\nprint(sys)\n"


def test_multiline_style_preserved():
    out = fix("""
    from os.path import (
        join,
        exists,
        isdir as is_dir,
    )
    print(join, is_dir)
    """)
    assert "from os.path import (\n    join,\n    isdir as is_dir,\n)\n" in out
