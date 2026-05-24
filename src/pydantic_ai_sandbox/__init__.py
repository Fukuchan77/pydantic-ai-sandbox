"""``pydantic_ai_sandbox`` — top-level package marker.

Public surface intentionally minimal at this stage of the SDD pipeline; the
agent / API / observability layers ship in later tasks (T4 onwards) and will
re-export their stable entry points from sub-packages, not from here. Only
``__version__`` is exposed so tooling and downstream code have a single,
stable place to read the package version.
"""

from __future__ import annotations

__all__ = ("__version__",)

__version__: str = "0.1.0"
