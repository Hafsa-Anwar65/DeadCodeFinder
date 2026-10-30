"""deadcode-finder: find (and safely remove) dead Python code."""

from .analyzer import Finding, analyze_paths, analyze_source
from .fixer import fix_unused_imports

__all__ = ["Finding", "analyze_paths", "analyze_source", "fix_unused_imports"]
__version__ = "0.1.0"
