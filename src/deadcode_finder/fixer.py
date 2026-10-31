"""Safe auto-fix: removes unused imports only.

Removing functions or classes can break code that uses them dynamically, so
those are reported but never deleted automatically.
"""

from __future__ import annotations

import ast
import difflib
from pathlib import Path

from .analyzer import Finding


def _line_is_only(lines: list[str], node: ast.stmt) -> bool:
    """True if the statement occupies its lines alone (no `a; b` on the same line)."""
    start, end = node.lineno - 1, (node.end_lineno or node.lineno) - 1
    before = lines[start][: node.col_offset]
    after = lines[end][node.end_col_offset or 0:]
    return before.strip() == "" and (after.strip() == "" or after.strip().startswith("#"))


def fix_source(source: str, findings: list[Finding]) -> str:
    """Return `source` with the unused imports from `findings` removed."""
    unused = {(f.line, f.name) for f in findings if f.kind == "unused-import"}
    if not unused:
        return source

    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    edits: list[tuple[int, int, list[str]]] = []  # (start_idx, end_idx_exclusive, new_lines)

    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    plans: list[tuple[ast.stmt, list[ast.alias]]] = []
    removed_fully: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        drop = [a for a in node.names
                if (node.lineno, a.asname or a.name.split(".")[0]) in unused]
        if not drop or not _line_is_only(lines, node):
            continue
        keep = [a for a in node.names if a not in drop]
        plans.append((node, keep))
        if not keep:
            removed_fully.add(id(node))

    def containing_block(node: ast.stmt) -> list[ast.stmt] | None:
        parent = parents.get(node)
        for attr in ("body", "orelse", "finalbody"):
            block = getattr(parent, attr, None)
            if isinstance(block, list) and node in block:
                return block
        return None

    for node, keep in plans:
        start, end = node.lineno - 1, node.end_lineno or node.lineno
        indent = lines[start][: node.col_offset]
        trailing = lines[end - 1][node.end_col_offset or 0:].rstrip("\r\n")
        newline = "\r\n" if lines[end - 1].endswith("\r\n") else "\n"

        if keep:
            kept_node = ast.ImportFrom(module=node.module, names=keep, level=node.level) \
                if isinstance(node, ast.ImportFrom) else ast.Import(names=keep)
            multiline = isinstance(node, ast.ImportFrom) and (node.end_lineno or 0) > node.lineno \
                and len(keep) > 1
            if multiline:  # keep the parenthesized one-name-per-line style
                head = "from " + "." * node.level + (node.module or "") + " import ("
                body = [f"{indent}    {ast.unparse(ast.ImportFrom(module='x', names=[a], level=0)).split(' import ', 1)[1]},{newline}"
                        for a in keep]
                new = [indent + head + newline, *body, indent + ")" + trailing + newline]
            else:
                new = [indent + ast.unparse(kept_node) + trailing + newline]
        else:
            new = []
            block = containing_block(node)
            # Never leave an empty block behind (e.g. imports inside try:).
            if (block is not None and not isinstance(parents.get(node), ast.Module)
                    and all(id(s) in removed_fully for s in block) and block[-1] is node):
                new = [indent + "pass" + newline]
        edits.append((start, end, new))

    for start, end, new in sorted(edits, reverse=True):
        lines[start:end] = new
    return "".join(lines)


def fix_unused_imports(findings: list[Finding], dry_run: bool = False) -> dict[str, str]:
    """Apply fixes to files on disk. Returns {path: unified_diff} for changed files."""
    by_path: dict[str, list[Finding]] = {}
    for f in findings:
        if f.kind == "unused-import" and f.fixable:
            by_path.setdefault(f.path, []).append(f)

    diffs: dict[str, str] = {}
    for path, items in by_path.items():
        p = Path(path)
        original = p.read_text(encoding="utf-8")
        updated = fix_source(original, items)
        if updated == original:
            continue
        try:
            ast.parse(updated)  # safety net: never write code that doesn't parse
        except SyntaxError:
            continue
        diffs[path] = "".join(difflib.unified_diff(
            original.splitlines(keepends=True), updated.splitlines(keepends=True),
            fromfile=f"a/{path.lstrip('/')}", tofile=f"b/{path.lstrip('/')}",
        ))
        if not dry_run:
            p.write_text(updated, encoding="utf-8")
    return diffs
