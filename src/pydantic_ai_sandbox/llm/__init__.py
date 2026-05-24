"""LLM abstraction layer (plan.md §2.2).

Re-exports :func:`get_model` so callers (FastAPI ``Depends`` factories,
agent builders, integration tests) import from a single, stable surface:

    from pydantic_ai_sandbox.llm import get_model

The provider-specific builders under ``providers/`` are intentionally
private to this package — outside callers MUST go through ``get_model``
so the env-driven dispatch table stays the single source of truth.
"""

from __future__ import annotations

from pydantic_ai_sandbox.llm.factory import get_model

__all__ = ["get_model"]
