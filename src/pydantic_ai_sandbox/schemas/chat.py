"""Pydantic schemas for the ``/chat`` request/response wire contract.

plan.md §2.6 fixes the shape:

* ``ChatRequest.message`` carries the user's natural-language prompt and
  is constrained to at least one character so the FastAPI 422 path
  (Req 3.6) catches empty bodies without reaching the agent.
* ``ChatResponse.answer`` carries the free-form textual answer, and
  ``ChatResponse.sources`` carries the structured "at least one
  structured field" required by Req 3.2. Defaulting ``sources`` to an
  empty list lets a model legitimately return no citations without
  needing to thread a ``None`` through ``output_type`` validation, which
  Pydantic AI V2's structured-output coercion treats as a hard schema
  violation.

The classes are intentionally minimal: §2.6 explicitly says "NOT owned:
バリデーション以外のロジック". Anything beyond field declarations and
docstrings belongs in a different module.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Wire shape for ``POST /chat`` request bodies.

    Attributes:
        message: User-supplied natural-language prompt. Constrained to
            ``min_length=1`` so the FastAPI request validator returns
            422 (Req 3.6) for empty strings before the agent runs.
    """

    message: str = Field(
        min_length=1,
        description="User-supplied natural-language prompt routed into the chat agent.",
    )


class ChatResponse(BaseModel):
    """Wire shape for ``POST /chat`` response bodies.

    Attributes:
        answer: Free-form textual answer produced by the agent.
        sources: Structured citation list (Req 3.2 "at least one
            structured field beyond a free-text answer"). Defaults to an
            empty list so a no-citation reply remains schema-valid; the
            ``search_kb`` tool stub is responsible for populating
            entries when invoked.
    """

    answer: str = Field(
        description="Agent-generated natural-language answer addressed to the caller.",
    )
    sources: list[str] = Field(
        default_factory=list,
        description="Citations or knowledge-base identifiers backing the answer.",
    )
