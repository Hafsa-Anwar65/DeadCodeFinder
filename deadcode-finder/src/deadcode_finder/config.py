"""Reads [tool.deadcode-finder] from pyproject.toml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:
        tomllib = None  # type: ignore[assignment]


@dataclass
class Config:
    paths: list[str] = field(default_factory=lambda: ["."])
    exclude: list[str] = field(default_factory=list)
    ignore_names: list[str] = field(default_factory=list)
    min_confidence: int = 60


def find_pyproject(start: Path) -> Path | None:
    for directory in [start, *start.parents]:
        candidate = directory / "pyproject.toml"
        if candidate.is_file():
            return candidate
    return None


def load_config(start: Path | None = None) -> Config:
    cfg = Config()
    path = find_pyproject((start or Path.cwd()).resolve())
    if path is None or tomllib is None:
        return cfg
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return cfg
    section = data.get("tool", {}).get("deadcode-finder", {})
    cfg.paths = list(section.get("paths", cfg.paths))
    cfg.exclude = list(section.get("exclude", cfg.exclude))
    cfg.ignore_names = list(section.get("ignore-names", section.get("ignore_names", cfg.ignore_names)))
    cfg.min_confidence = int(section.get("min-confidence", section.get("min_confidence", cfg.min_confidence)))
    return cfg
