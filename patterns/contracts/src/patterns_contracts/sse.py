"""SSE delivery-layer event contracts (Spec 008-2c Req 2.1, 2.3, 8.3).

This module is the single source of truth for the five agent-execution event
models and the ``SseEvent`` discriminated union; the normative copy also lives
in ``patterns/sse/README.md`` fenced block, asserted equal by the single-point
drift test once the ``sse`` README is registered (Task 11). The SSE lane
(``patterns_sse``) imports these via the ``patterns/contracts`` path dependency
rather than duplicating them (NFR-3).

SSE is a *delivery-infrastructure application layer*, not one of the six
workflow patterns. Each event carries a ``type: Literal[...]`` discriminator
that doubles as the SSE ``event:`` name (Req 2.3); ``SseEvent`` is the tagged
union pydantic dispatches on, so the wire ``data:`` JSON round-trips back to the
exact member.

Security (Req 8.3): the field set is deliberately minimal. No model carries the
raw prompt, full traceback, or any credential -- ``ToolCalledEvent.args_json``
and ``ErrorEvent.message`` are sanitized summaries the *producer* is responsible
for keeping secret-free. The contract stays a plain, dependency-zero shape; the
sanitization is enforced upstream, not as a field constraint here.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

__all__ = [
    "CompletedEvent",
    "ErrorEvent",
    "SseEvent",
    "StepStartedEvent",
    "TokenEvent",
    "ToolCalledEvent",
]


class StepStartedEvent(BaseModel):
    """An execution step began (e.g. ``classify`` / ``answer``)."""

    type: Literal["step_started"] = "step_started"
    step: str = Field(description="Name of the step that started (e.g. classify / answer).")


class ToolCalledEvent(BaseModel):
    """A tool was invoked during execution."""

    type: Literal["tool_called"] = "tool_called"
    tool: str = Field(description="Name of the invoked tool.")
    args_json: str = Field(
        description="Sanitized JSON string of the call arguments; no secrets (R8.3)."
    )


class TokenEvent(BaseModel):
    """An incremental output token (fixed chunks make it deterministic, R5.3)."""

    type: Literal["token"] = "token"
    text: str = Field(description="The incremental token text.")


class CompletedEvent(BaseModel):
    """Final output; a terminal marker that ends the stream cleanly (R4.4)."""

    type: Literal["completed"] = "completed"
    output: str = Field(description="The final agent output.")


class ErrorEvent(BaseModel):
    """A run-time error; a terminal marker that ends the stream (R4.3, R4.4)."""

    type: Literal["error"] = "error"
    message: str = Field(description="Exception summary; no full traceback or credentials (R8.3).")


SseEvent = Annotated[
    StepStartedEvent | ToolCalledEvent | TokenEvent | CompletedEvent | ErrorEvent,
    Field(discriminator="type"),
]
"""Discriminated union of the five SSE events, tagged by ``type`` (R2.1).

The ``event:`` name on the wire is the active member's ``type`` discriminator
(R2.3); ``TypeAdapter(SseEvent).validate_json`` reverses a ``data:`` line back
to the matching model. The drift parser skips this ``Annotated`` alias (it is
neither a model class nor a ``Literal``), matching the ``ApprovalHook`` Callable
alias precedent (research.md I-5)."""
