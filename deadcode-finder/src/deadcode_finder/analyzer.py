"""Static analysis that finds dead code in Python projects.

The analysis is purely AST based (no code is imported or executed), so it is
safe to run on any repository.

Detected kinds:
    unused-import     an imported name that is never used in its file
    unused-variable   a local variable that is assigned but never read
    unused-function   a function never referenced anywhere in the project
    unused-class      a class never referenced anywhere in the project
    unused-method     a method never referenced anywhere in the project
    unreachable-code  statements after return / raise / break / continue
"""

from __future__ import annotations

import ast
import fnmatch
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

IGNORE_COMMENT = re.compile(r"#\s*(deadcode|dcf)\s*:\s*ignore", re.IGNORECASE)
# flake8/ruff style "this import is intentional" markers
NOQA_IMPORT = re.compile(r"#\s*noqa(?!\s*:)|#\s*noqa\s*:[^#]*\bF401\b", re.IGNORECASE)
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

DEFAULT_EXCLUDE_DIRS = {
    ".git", ".hg", ".svn", ".tox", ".nox", ".venv", "venv", "env", ".env",
    "__pycache__", "build", "dist", "node_modules", "site-packages",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".eggs",
}

# Methods called implicitly by Python, frameworks or test runners.
IMPLICIT_METHODS = {
    "setUp", "tearDown", "setUpClass", "tearDownClass", "setUpModule",
    "tearDownModule", "asyncSetUp", "asyncTearDown", "run", "main",
    "save", "clean", "get", "post", "put", "patch", "delete", "dispatch",
    "handle", "emit", "default", "visit", "generic_visit",
}

# Visitor / command / event-handler patterns dispatched by name at runtime.
IMPLICIT_PREFIXES = ("visit_", "leave_", "depart_", "do_", "on_", "handle_", "test_")

CONFIDENCE = {
    "unused-import": 95,
    "unreachable-code": 100,
    "unused-variable": 90,
    "unused-function": 70,
    "unused-class": 70,
    "unused-method": 60,
}
UNPACKED_CONFIDENCE = 60  # tip: name it `_` to silence
DECORATED_CONFIDENCE = 40  # decorators often register functions (routes, CLI, fixtures)


@dataclass
class Finding:
    path: str
    line: int
    end_line: int
    kind: str
    name: str
    message: str
    confidence: int
    fixable: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class _Definition:
    path: str
    node: ast.AST
    kind: str
    name: str
    decorated: bool


@dataclass
class _FileInfo:
    path: str
    source: str
    tree: ast.Module
    lines: list[str]
    used_names: set[str] = field(default_factory=set)
    exported: set[str] = field(default_factory=set)


def _is_ignored(lines: list[str], lineno: int) -> bool:
    if 1 <= lineno <= len(lines):
        return bool(IGNORE_COMMENT.search(lines[lineno - 1]))
    return False


def _is_dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")


def _collect_exports(tree: ast.Module) -> set[str]:
    """Names listed in __all__ = [...] (also handles += and tuples)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        targets: list[ast.AST] = []
        value = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets, value = [node.target], node.value
        if value is None:
            continue
        if any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
            if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
                for elt in value.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        names.add(elt.value)
    return names


def _collect_used_names(tree: ast.Module) -> set[str]:
    """Every name that is read anywhere in a module.

    Attribute names (obj.method) and identifier-like string constants
    (getattr(obj, "name"), string type hints) also count as usage, which keeps
    false positives low for dynamic code.
    """
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            # `from .core import thing` references `thing` (e.g. a public re-export in __init__.py)
            used.update(a.name for a in node.names)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Load, ast.Del)):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
            if IDENTIFIER.match(text):
                used.add(text)
            elif len(text) < 200:
                # string annotations like "Optional[Foo]" or "pkg.Foo"
                used.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text))
    return used


def _import_bindings(node: ast.Import | ast.ImportFrom) -> list[tuple[ast.alias, str]]:
    bindings = []
    for alias in node.names:
        if alias.name == "*":
            continue
        bound = alias.asname or alias.name.split(".")[0]
        bindings.append((alias, bound))
    return bindings


def _is_type_checking_block(node: ast.AST) -> bool:
    if isinstance(node, ast.If):
        test = node.test
        if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
            return True
        if isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING":
            return True
    return False


def _find_unused_imports(info: _FileInfo, reexported: set[str] = frozenset()) -> list[Finding]:
    findings: list[Finding] = []
    is_init = os.path.basename(info.path) == "__init__.py"
    if is_init:
        return findings  # imports in __init__ are usually public re-exports

    # Only the names *loaded* in this file count for imports.
    loaded: set[str] = set()
    for node in ast.walk(info.tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Load, ast.Del)):
            loaded.add(node.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) < 200:
            loaded.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", node.value))
    loaded |= info.exported

    for node in ast.walk(info.tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            continue
        if _is_ignored(info.lines, node.lineno):
            continue
        span = info.lines[node.lineno - 1:(node.end_lineno or node.lineno)]
        if any(NOQA_IMPORT.search(line) for line in span):
            continue
        for alias, bound in _import_bindings(node):
            # "import x as x" / "from y import x as x" is the explicit re-export idiom
            if alias.asname and alias.asname == alias.name:
                continue
            if bound in loaded or bound in reexported:
                continue  # used here, or imported from this module by another file
            shown = alias.name if not alias.asname else f"{alias.name} as {alias.asname}"
            findings.append(Finding(
                path=info.path, line=node.lineno, end_line=node.end_lineno or node.lineno,
                kind="unused-import", name=bound,
                message=f"unused import '{shown}'",
                confidence=CONFIDENCE["unused-import"], fixable=True,
            ))
    return findings


class _FunctionScope(ast.NodeVisitor):
    """Collects stores and loads of plain names inside one function body,
    without descending into nested functions/classes (they are visited on their own)."""

    def __init__(self) -> None:
        self.stores: dict[str, ast.AST] = {}
        self.loads: set[str] = set()
        self.dynamic = False  # locals()/vars()/exec/eval make analysis unreliable
        self.declared: set[str] = set()
        self.unpacked: set[str] = set()

    def visit_FunctionDef(self, node):  # nested def: its name is a local store
        self.stores.setdefault(node.name, node)
        for dec in node.decorator_list:
            self.visit(dec)
        # Free variables of nested functions count as loads of this scope.
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                self.loads.add(sub.id)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node):
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                self.loads.add(sub.id)

    def visit_ClassDef(self, node):
        self.stores.setdefault(node.name, node)
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                self.loads.add(sub.id)

    def visit_Global(self, node):
        self.declared.update(node.names)

    visit_Nonlocal = visit_Global

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id in {"locals", "vars", "exec", "eval"}:
            self.dynamic = True
        self.generic_visit(node)

    def visit_Tuple(self, node):
        if isinstance(node.ctx, ast.Store):  # a, b = ... : unpacking is often intentional
            self.unpacked.update(e.id for e in node.elts if isinstance(e, ast.Name))
        self.generic_visit(node)

    visit_List = visit_Tuple

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Store):
            self.stores.setdefault(node.id, node)
        else:
            self.loads.add(node.id)


def _find_unused_variables(info: _FileInfo) -> list[Finding]:
    findings: list[Finding] = []
    for func in ast.walk(info.tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        scope = _FunctionScope()
        for stmt in func.body:
            scope.visit(stmt)
        if scope.dynamic:
            continue
        for name, node in scope.stores.items():
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue  # nested definitions are reported (if at all) elsewhere
            if name.startswith("_") or name in scope.loads or name in scope.declared:
                continue
            lineno = getattr(node, "lineno", func.lineno)
            if _is_ignored(info.lines, lineno):
                continue
            findings.append(Finding(
                path=info.path, line=lineno, end_line=lineno,
                kind="unused-variable", name=name,
                message=f"local variable '{name}' is assigned but never used (in {func.name}())",
                confidence=UNPACKED_CONFIDENCE if name in scope.unpacked else CONFIDENCE["unused-variable"],
            ))
    return findings


_TERMINAL = (ast.Return, ast.Raise, ast.Continue, ast.Break)


def _find_unreachable(info: _FileInfo) -> list[Finding]:
    findings: list[Finding] = []

    def check_block(body: list[ast.stmt]) -> None:
        for i, stmt in enumerate(body):
            if isinstance(stmt, _TERMINAL) and i + 1 < len(body):
                first, last = body[i + 1], body[-1]
                if _is_ignored(info.lines, first.lineno):
                    break
                what = type(stmt).__name__.lower()
                findings.append(Finding(
                    path=info.path, line=first.lineno,
                    end_line=getattr(last, "end_lineno", None) or last.lineno,
                    kind="unreachable-code", name=f"after-{what}",
                    message=f"unreachable code after '{what}'",
                    confidence=CONFIDENCE["unreachable-code"],
                ))
                break

    for node in ast.walk(info.tree):
        for attr in ("body", "orelse", "finalbody"):
            block = getattr(node, attr, None)
            if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
                check_block(block)  # ExceptHandler / match_case bodies are walked too
    return findings


def _collect_definitions(info: _FileInfo) -> list[_Definition]:
    defs: list[_Definition] = []

    def visit(body: list[ast.stmt], in_class: bool) -> None:
        for node in body:
            if _is_type_checking_block(node):
                continue
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = "unused-method" if in_class else "unused-function"
                defs.append(_Definition(info.path, node, kind, node.name, bool(node.decorator_list)))
            elif isinstance(node, ast.ClassDef):
                defs.append(_Definition(info.path, node, "unused-class", node.name, bool(node.decorator_list)))
                visit(node.body, in_class=True)
            elif isinstance(node, (ast.If, ast.Try)):
                visit(node.body, in_class)
                visit(getattr(node, "orelse", []), in_class)
                for handler in getattr(node, "handlers", []):
                    visit(handler.body, in_class)

    visit(info.tree.body, in_class=False)
    return defs


def _is_test_file(path: str) -> bool:
    base = os.path.basename(path)
    return base.startswith("test_") or base.endswith("_test.py") or base == "conftest.py"


def _skip_definition(d: _Definition) -> bool:
    name = d.name
    if _is_dunder(name):
        return True
    if _is_test_file(d.path) and (name.startswith("test") or name.startswith("Test")):
        return True
    if d.kind == "unused-method" and (name in IMPLICIT_METHODS or name.startswith(IMPLICIT_PREFIXES)):
        return True
    if d.kind == "unused-method" and isinstance(d.node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for dec in d.node.decorator_list:
            target = dec.func if isinstance(dec, ast.Call) else dec
            label = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
            if label in {"override", "abstractmethod", "setter", "getter", "deleter"}:
                return True
    return False


def _module_stem(path: str) -> str:
    p = Path(path)
    return p.parent.name if p.name == "__init__.py" else p.stem


def _parse(path: str, source: str) -> _FileInfo | None:
    try:
        tree = ast.parse(source, filename=path)
    except (SyntaxError, ValueError):
        return None
    info = _FileInfo(path=path, source=source, tree=tree, lines=source.splitlines())
    info.used_names = _collect_used_names(tree)
    info.exported = _collect_exports(tree)
    return info


def _analyze_infos(infos: list[_FileInfo]) -> list[Finding]:
    findings: list[Finding] = []
    project_used: set[str] = set()
    project_exported: set[str] = set()
    # (module_stem, name) pairs that files pull in from *project* modules,
    # e.g. `from .compat import json` -> ("compat", "json"). An "unused" import in
    # compat.py that others import from it is a re-export, not dead code.
    stems = {_module_stem(i.path) for i in infos}
    imported_from: set[tuple[str, str]] = set()
    for info in infos:
        project_used |= info.used_names
        project_exported |= info.exported
        for node in ast.walk(info.tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                target = node.module.split(".")[-1]
                if node.level or target in stems:
                    imported_from.update((target, a.name) for a in node.names)

    for info in infos:
        stem = _module_stem(info.path)
        findings += _find_unused_imports(info, {n for m, n in imported_from if m == stem})
        findings += _find_unused_variables(info)
        findings += _find_unreachable(info)

        for d in _collect_definitions(info):
            if _skip_definition(d) or d.name in project_used or d.name in project_exported:
                continue
            if _is_ignored(info.lines, d.node.lineno):
                continue
            label = d.kind.split("-", 1)[1]
            confidence = DECORATED_CONFIDENCE if d.decorated else CONFIDENCE[d.kind]
            if d.name.startswith("_") and not d.decorated:
                confidence = min(100, confidence + 10)  # private + unused = very likely dead
            findings.append(Finding(
                path=info.path, line=d.node.lineno,
                end_line=getattr(d.node, "end_lineno", None) or d.node.lineno,
                kind=d.kind, name=d.name,
                message=f"unused {label} '{d.name}'",
                confidence=confidence,
            ))

    findings.sort(key=lambda f: (f.path, f.line, f.kind))
    return findings


def iter_python_files(paths: Iterable[str], exclude: Iterable[str] = ()) -> Iterator[str]:
    """Yield .py files under the given paths, skipping virtualenvs, caches and excludes."""
    patterns = list(exclude)

    def excluded(p: str) -> bool:
        norm = p.replace(os.sep, "/")
        return any(fnmatch.fnmatch(norm, pat) or fnmatch.fnmatch(os.path.basename(p), pat)
                   or fnmatch.fnmatch(norm, f"*/{pat}") or fnmatch.fnmatch(norm, f"*/{pat}/*")
                   for pat in patterns)

    seen: set[str] = set()
    for root in paths:
        root_path = Path(root)
        if root_path.is_file():
            if root_path.suffix == ".py" and not excluded(str(root_path)):
                seen.add(str(root_path))
                yield str(root_path)
            continue
        for dirpath, dirnames, filenames in os.walk(root_path):
            dirnames[:] = sorted(
                d for d in dirnames
                if d not in DEFAULT_EXCLUDE_DIRS and not d.endswith(".egg-info")
                and not excluded(os.path.join(dirpath, d))
            )
            for fname in sorted(filenames):
                full = os.path.join(dirpath, fname)
                if fname.endswith(".py") and full not in seen and not excluded(full):
                    seen.add(full)
                    yield full


def analyze_paths(
    paths: Iterable[str],
    exclude: Iterable[str] = (),
    min_confidence: int = 60,
    ignore_names: Iterable[str] = (),
) -> tuple[list[Finding], list[str]]:
    """Analyze files/directories. Returns (findings, files_that_failed_to_parse)."""
    infos: list[_FileInfo] = []
    errors: list[str] = []
    for path in iter_python_files(paths, exclude):
        try:
            source = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            errors.append(path)
            continue
        info = _parse(path, source)
        if info is None:
            errors.append(path)
        else:
            infos.append(info)
    return _filter(_analyze_infos(infos), min_confidence, ignore_names), errors


def analyze_source(source: str, path: str = "<string>", min_confidence: int = 0,
                   ignore_names: Iterable[str] = ()) -> list[Finding]:
    """Analyze a single piece of source code (handy for tests and editors)."""
    info = _parse(path, source)
    if info is None:
        raise SyntaxError(f"could not parse {path}")
    return _filter(_analyze_infos([info]), min_confidence, ignore_names)


def _filter(findings: list[Finding], min_confidence: int, ignore_names: Iterable[str]) -> list[Finding]:
    patterns = list(ignore_names)
    return [
        f for f in findings
        if f.confidence >= min_confidence
        and not any(fnmatch.fnmatch(f.name, p) for p in patterns)
    ]
