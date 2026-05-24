"""Wire schemas for the public ``/chat`` API surface.

Re-exports :class:`ChatRequest` and :class:`ChatResponse` so callers
write ``from pydantic_ai_sandbox.schemas import ChatRequest`` instead of
reaching into the submodule. plan.md §4.1 lists the package under
"namespace のみ" — keep this file an export-only seam to avoid
accidentally accreting business logic at the package boundary.
"""

from __future__ import annotations

from pydantic_ai_sandbox.schemas.chat import ChatRequest, ChatResponse

__all__ = ["ChatRequest", "ChatResponse"]
