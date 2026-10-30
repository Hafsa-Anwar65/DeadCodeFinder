"""Command line interface: `deadcode-finder` (alias `dcf`)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .analyzer import CONFIDENCE, analyze_paths, iter_python_files
from .config import load_config
from .fixer import fix_unused_imports
from .reporters import render_github, render_html, render_json, render_text

KINDS = sorted(CONFIDENCE)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="deadcode-finder",
        description="Find unused imports, functions, classes, variables and unreachable code in Python projects.",
    )
    p.add_argument("paths", nargs="*", help="files or folders to scan (default: from config, else '.')")
    p.add_argument("--fix", action="store_true", help="remove unused imports in place (safe auto-fix)")
    p.add_argument("--diff", action="store_true", help="show what --fix would change, without writing")
    p.add_argument("-f", "--format", choices=["text", "json", "html", "github"], default="text",
                   help="output format (github = PR annotations in Actions)")
    p.add_argument("-o", "--output", help="write the report to this file instead of stdout")
    p.add_argument("-c", "--min-confidence", type=int, help="hide findings below this confidence (0-100, default 60)")
    p.add_argument("--only", action="append", choices=KINDS, metavar="KIND",
                   help=f"report only these kinds (repeatable): {', '.join(KINDS)}")
    p.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                   help="skip paths matching this glob (repeatable), e.g. 'migrations'")
    p.add_argument("--ignore-name", action="append", default=[], metavar="GLOB",
                   help="never report names matching this glob (repeatable), e.g. 'handle_*'")
    p.add_argument("--exit-zero", action="store_true", help="always exit 0, even if dead code is found")
    p.add_argument("--no-color", action="store_true", help="disable colored output")
    p.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config()

    paths = args.paths or cfg.paths
    exclude = cfg.exclude + args.exclude
    ignore_names = cfg.ignore_names + args.ignore_name
    min_conf = args.min_confidence if args.min_confidence is not None else cfg.min_confidence

    missing = [p for p in paths if not Path(p).exists()]
    if missing:
        print(f"deadcode-finder: path not found: {', '.join(missing)}", file=sys.stderr)
        return 2

    files_scanned = sum(1 for _ in iter_python_files(paths, exclude))
    findings, errors = analyze_paths(paths, exclude=exclude, min_confidence=min_conf, ignore_names=ignore_names)
    if args.only:
        findings = [f for f in findings if f.kind in args.only]
    for path in errors:
        print(f"deadcode-finder: skipped (could not parse): {path}", file=sys.stderr)

    if args.fix or args.diff:
        diffs = fix_unused_imports(findings, dry_run=args.diff)
        if args.diff:
            print("".join(diffs.values()) or "Nothing to fix.")
            return 0
        removed = sum(1 for f in findings if f.kind == "unused-import" and f.path in diffs)
        print(f"Removed {removed} unused import(s) in {len(diffs)} file(s).", file=sys.stderr)
        # Re-scan so the report shows what's left.
        findings, _ = analyze_paths(paths, exclude=exclude, min_confidence=min_conf, ignore_names=ignore_names)
        if args.only:
            findings = [f for f in findings if f.kind in args.only]

    color = (not args.no_color and not args.output and sys.stdout.isatty()
             and os.environ.get("NO_COLOR") is None)
    if args.format == "json":
        report = render_json(findings, files_scanned)
    elif args.format == "html":
        report = render_html(findings, files_scanned)
    elif args.format == "github":
        report = render_github(findings) + "\n" + render_text(findings, files_scanned)
    else:
        report = render_text(findings, files_scanned, color=color)

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"Report written to {args.output} ({len(findings)} issue(s)).", file=sys.stderr)
    else:
        print(report)

    return 0 if args.exit_zero or not findings else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
