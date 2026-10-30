# deadcode-finder

[![CI](https://github.com/Hafsa-Anwar65/deadcode-finder/actions/workflows/ci.yml/badge.svg)](https://github.com/Hafsa-Anwar65/deadcode-finder/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)

**Find and safely remove dead Python code.** Unused imports, functions, classes, methods, local variables and unreachable code — with a confidence score on every finding, a safe auto-fix, and inline annotations on your pull requests.

```text
$ deadcode-finder .
app/api.py:3: unused-import unused import 'json' (95% confidence) [fixable]
app/api.py:41: unused-variable local variable 'tmp' is assigned but never used (in handler()) (90% confidence)
app/api.py:58: unreachable-code unreachable code after 'return' (100% confidence)
app/utils.py:12: unused-function unused function '_old_helper' (80% confidence)
app/models.py:30: unused-class unused class 'LegacyUser' (70% confidence)

Found 5 issue(s) in 24 file(s): 1 unused-import, 1 unused-variable, 1 unreachable-code, 1 unused-function, 1 unused-class
1 can be removed automatically with --fix
```

## Why

Every project collects code nobody calls anymore: imports left after a refactor, helpers replaced months ago, a `print` after a `return`. Dead code makes a repo harder to read, slower to review, and hides real bugs. `deadcode-finder` scans your project statically (it never imports or runs your code) and tells you exactly what's safe to delete.

- **Zero dependencies** — pure standard library (`ast`)
- **Project-wide** — a function is only "unused" if no file in the project references it
- **Low noise** — understands `__all__`, `# noqa: F401`, re-exports, dunder methods, test functions, visitor methods (`visit_*`), decorators (routes, fixtures, CLI commands get low confidence), `getattr(obj, "name")` and string type hints
- **Safe auto-fix** — `--fix` only removes unused imports, keeps your formatting and comments, never leaves an empty block, and refuses to write anything that doesn't parse
- **CI ready** — exit code `1` on findings, GitHub PR annotations, HTML/JSON reports, pre-commit hook, Docker image

## Install

```bash
pip install git+https://github.com/Hafsa-Anwar65/deadcode-finder.git
```

Or with Docker (GitHub Packages):

```bash
docker run --rm -v "$PWD:/code" ghcr.io/hafsa-anwar65/deadcode-finder
```

## Usage

```bash
deadcode-finder                      # scan the current folder (or paths from pyproject.toml)
deadcode-finder src tests            # scan specific paths
dcf .                                # short alias

deadcode-finder . --diff             # preview what --fix would remove
deadcode-finder . --fix              # remove unused imports in place

deadcode-finder . -c 90              # only high-confidence findings
deadcode-finder . --only unused-import --only unreachable-code
deadcode-finder . --exclude migrations --exclude "*_pb2.py"
deadcode-finder . --ignore-name "handle_*"

deadcode-finder . -f html -o deadcode-report.html   # shareable HTML report
deadcode-finder . -f json                           # machine-readable output
```

| Kind | What it means | Confidence |
|---|---|---|
| `unreachable-code` | statements after `return` / `raise` / `break` / `continue` | 100 |
| `unused-import` | imported but never used in that file *(auto-fixable)* | 95 |
| `unused-variable` | local variable assigned but never read | 90 (60 for tuple unpacking) |
| `unused-function` | never referenced anywhere in the project | 70 (80 if `_private`) |
| `unused-class` | never referenced anywhere in the project | 70 |
| `unused-method` | never referenced anywhere in the project | 60 |
| *decorated function/class* | may be registered by a framework | 40 |

Default threshold is **60**. Use `-c 0` to see everything.

### Exit codes

`0` clean · `1` dead code found · `2` bad path. Add `--exit-zero` to never fail.

## Silencing findings

```python
import socket  # noqa: F401        (flake8/ruff style, respected)
import ssl     # deadcode: ignore

def plugin_entry():  # dcf: ignore
    ...

def split(pair):
    _, value = pair    # name it `_` (or `_anything`) to mark it intentionally unused
    return value
```

Public library API that nothing in the repo calls? List it in `__all__`, or use `--ignore-name`.

## Configuration

Add to your `pyproject.toml`:

```toml
[tool.deadcode-finder]
paths = ["src"]
exclude = ["migrations", "*_pb2.py"]
ignore-names = ["handle_*", "Meta"]
min-confidence = 70
```

## GitHub Action

Shows dead code as inline annotations on pull requests:

```yaml
# .github/workflows/deadcode.yml
name: Dead code
on: [pull_request]
jobs:
  deadcode:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: Hafsa-Anwar65/deadcode-finder@v0.1.0
        with:
          paths: src
          min-confidence: 70
          fail-on-findings: true
          # html-report: deadcode-report.html
```

## pre-commit

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/Hafsa-Anwar65/deadcode-finder
    rev: v0.1.0
    hooks:
      - id: deadcode-finder-fix   # removes unused imports on commit
      - id: deadcode-finder       # reports everything else
```

## Python API

```python
from deadcode_finder import analyze_paths, analyze_source, fix_unused_imports

findings, unparseable = analyze_paths(["src"], min_confidence=70)
for f in findings:
    print(f.path, f.line, f.kind, f.name, f.confidence)

fix_unused_imports(findings)             # apply the safe fixes
analyze_source("import os\n")           # analyze a string
```

## Limitations

Static analysis can't see everything. Code used only through dynamic tricks (`importlib`, plugin entry points, names built from strings) or called by *other* projects (public library APIs) may be reported. That's why every finding has a confidence score and why `--fix` only touches imports. Review before deleting functions or classes.

## Development

```bash
git clone https://github.com/Hafsa-Anwar65/deadcode-finder.git
cd deadcode-finder
pip install -e ".[dev]"
pytest
deadcode-finder        # it scans itself — and it's clean
```

## License

MIT © 2026 Hafsa Anwar
