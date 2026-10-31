# Changelog

## 0.1.0 — 2026-10-30

First release.

- Detects unused imports, functions, classes, methods, local variables and unreachable code
- Confidence score on every finding, with `--min-confidence` filtering
- Safe `--fix` that removes unused imports only (verifies the result still parses); `--diff` preview
- Text, JSON, HTML and GitHub Actions annotation output
- Respects `# noqa: F401`, `# deadcode: ignore`, `__all__`, and project-internal re-exports
- Config via `[tool.deadcode-finder]` in `pyproject.toml`
- GitHub Action, pre-commit hooks and Docker image (ghcr.io)
