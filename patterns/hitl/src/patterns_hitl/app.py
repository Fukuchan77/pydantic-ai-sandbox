"""FastAPI app-factory for the HITL stop/approve/resume harness (Task 6.2).

``create_app`` is the DI seam (plan.md HitlApp, mirroring the sse lane's
``create_app(*, event_source, tracer_provider=None)``): callers inject an
already-built ``Agent`` and, optionally, a ``SessionStore`` -- the harness
is assembled internally from that pair, so unit tests drive the full
``/run`` -> ``/resume`` round trip with zero real provider I/O (R8.6,
R10.4) and the gated live-Ollama lane (Task 8) reuses the exact same
factory with a real model.

Two endpoints:

* ``POST /run`` starts a fresh agent run from a prompt and returns either
  a completed ``SupportOutput`` or a ``pending_approval`` payload naming
  the session and the tool calls awaiting a decision (R8.1, R8.2).
* ``POST /resume`` maps each caller ``Decision`` to pydantic-ai's own
  ``ToolApproved``/``ToolDenied`` and resumes the named session, returning
  the same two-shape response -- a further approval-gated tool call
  re-defers rather than looping in-process, since the approver lives
  outside this process (R8.3, R6.1). An unknown ``session_id`` is a
  ``404`` (R8.5); it is never conflated with a validation error.

Observability is opt-in per app instance via ``instrument`` -- the
lifespan calls :func:`patterns_hitl.observability.enable_observability`
fail-soft when set, so a broken Logfire/OTel install never blocks startup
(R9.1); unit tests other than ``test_observability.py`` pass
``instrument=False`` to skip the bootstrap entirely.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Literal

from fastapi import FastAPI, HTTPException

# Runtime import (not TYPE_CHECKING): pydantic resolves `CompletedResponse.output`
# when it builds the model schema, so the real type must be importable at
# class-definition time even under `from __future__ import annotations`.
from patterns_contracts import SupportOutput  # noqa: TC002  # used in a pydantic field
from pydantic import BaseModel, model_validator
from pydantic_ai import ToolApproved, ToolDenied

from .harness import HitlHarness, PendingResult
from .observability import enable_observability
from .store import SessionStore

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from pydantic_ai import Agent, DeferredToolRequests

    from .agent import HitlDeps

__all__ = ["create_app"]


class RunRequest(BaseModel):
    """Request body for ``POST /run``."""

    prompt: str


class PendingApproval(BaseModel):
    """One tool call awaiting a human decision, mapped from pydantic-ai's ``ToolCallPart``."""

    tool_call_id: str
    tool_name: str
    args: dict[str, Any] | str | None


class CompletedResponse(BaseModel):
    """A run that reached a terminal, structured answer."""

    status: Literal["completed"] = "completed"
    output: SupportOutput


class PendingResponse(BaseModel):
    """A run stopped with one or more approval-gated tool calls awaiting a decision."""

    status: Literal["pending_approval"] = "pending_approval"
    session_id: str
    approvals: list[PendingApproval]


class Decision(BaseModel):
    """A caller's resolution for one pending tool call, keyed by ``tool_call_id`` in ``ResumeRequest``."""

    approved: bool
    override_args: dict[str, Any] | None = None
    message: str | None = None

    @model_validator(mode="after")
    def _check_mutually_exclusive_fields(self) -> Decision:
        """Reject an ``override_args``/``message`` combination the wrong ``approved`` value never uses.

        Raises:
            ValueError: If ``approved=True`` carries a denial ``message``,
                or ``approved=False`` carries ``override_args`` -- either
                combination signals a caller mistake rather than a valid
                decision, so it is rejected as a ``422`` rather than
                silently ignored (plan.md Error Handling & Edge Cases).
        """
        if self.approved and self.message is not None:
            msg = "message is only valid when approved is False"
            raise ValueError(msg)
        if not self.approved and self.override_args is not None:
            msg = "override_args is only valid when approved is True"
            raise ValueError(msg)
        return self


class ResumeRequest(BaseModel):
    """Request body for ``POST /resume``."""

    session_id: str
    decisions: dict[str, Decision]


def _to_pending_response(result: PendingResult) -> PendingResponse:
    """Map a harness ``PendingResult`` onto the HTTP ``pending_approval`` shape."""
    return PendingResponse(
        session_id=result.session_id,
        approvals=[
            PendingApproval(
                tool_call_id=call.tool_call_id, tool_name=call.tool_name, args=call.args
            )
            for call in result.approvals
        ],
    )


def _to_deferred_result(decision: Decision) -> ToolApproved | ToolDenied:
    """Map a caller ``Decision`` onto pydantic-ai's own approval/denial types."""
    if decision.approved:
        return ToolApproved(override_args=decision.override_args)
    if decision.message is not None:
        return ToolDenied(decision.message)
    return ToolDenied()


def create_app(
    *,
    agent: Agent[HitlDeps, SupportOutput | DeferredToolRequests],
    store: SessionStore | None = None,
    instrument: bool = True,
) -> FastAPI:
    """Build the HITL FastAPI app with the agent (and optionally the store) injected.

    Args:
        agent: The agent to run, typically built by
            :func:`patterns_hitl.agent.build_agent`. Tests inject a
            ``FunctionModel``/``TestModel``-backed agent for zero-I/O
            coverage of the full ``/run`` -> ``/resume`` round trip.
        store: Where stopped runs' history and usage are carried across
            the stop/resume boundary; a fresh :class:`SessionStore` is
            created when omitted.
        instrument: When ``True``, the lifespan calls
            :func:`patterns_hitl.observability.enable_observability`
            fail-soft on startup (R9.1). Tests other than
            ``test_observability.py`` pass ``False`` to skip it.

    Returns:
        A FastAPI app exposing ``POST /run`` and ``POST /resume``.
    """
    harness = HitlHarness(agent, store or SessionStore())

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
        if instrument:
            enable_observability(app)
        yield

    app = FastAPI(lifespan=_lifespan)

    # Nested so each closes over the per-app `harness`; the `@app.post`
    # decorator registers it, which pyright cannot see through.
    @app.post("/run")
    async def run(  # pyright: ignore[reportUnusedFunction]
        body: RunRequest,
    ) -> CompletedResponse | PendingResponse:
        """Start a fresh agent run from ``body.prompt`` (R8.1, R8.2)."""
        result = await harness.start(body.prompt)
        if isinstance(result, PendingResult):
            return _to_pending_response(result)
        return CompletedResponse(output=result.output)

    @app.post("/resume")
    async def resume(  # pyright: ignore[reportUnusedFunction]
        body: ResumeRequest,
    ) -> CompletedResponse | PendingResponse:
        """Resume ``body.session_id`` with the caller's decisions (R8.3, R8.5)."""
        decisions = {
            tool_call_id: _to_deferred_result(decision)
            for tool_call_id, decision in body.decisions.items()
        }
        try:
            result = await harness.resume(body.session_id, decisions)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail=f"unknown session_id: {exc.args[0]}"
            ) from exc
        if isinstance(result, PendingResult):
            return _to_pending_response(result)
        return CompletedResponse(output=result.output)

    return app
