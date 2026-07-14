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

Spec 013 (R1.2, R2) extends both handlers with the consumption state
machine's HTTP mapping (research.md AD-2):

* An unknown, in-flight, or already-consumed ``session_id`` is a fixed,
  content-free ``404`` -- it never echoes the id or distinguishes *why*
  the claim failed (existence secrecy, R1.2).
* A ``/resume`` decision naming a ``tool_call_id`` the session did not
  actually defer is a ``409``, checked synchronously between ``claim()``
  and the ``await`` into the harness so no tool executes and the whole
  decision set is rejected together, not just the offending key (R2.3).
* A budget overrun (``HitlBudgetExceededError``, raised by both
  ``harness.start()`` and ``harness.resume()``) is a ``429`` on either
  route; ``/run`` never persisted a session to begin with, and
  ``/resume``'s session is already consumed by the harness before this
  is raised (R2.4).

Spec 013 R3 adds one :func:`patterns_hitl.audit.build_audit_event` call
per decision on ``/resume``, before the ``await`` into the harness --
emission runs through :func:`patterns_hitl.audit.emit_audit_event`'s
fail-soft boundary, so a broken ``audit_emitter`` (the default
``LogfireAuditEmitter`` or a caller-supplied one) never blocks or fails
the resume it is only observing (R3.4).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Literal

from fastapi import FastAPI, HTTPException

# Runtime import (not TYPE_CHECKING): pydantic resolves `CompletedResponse.output`
# when it builds the model schema, so the real type must be importable at
# class-definition time even under `from __future__ import annotations`.
from patterns_contracts import SupportOutput  # noqa: TC002  # used in a pydantic field
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_ai import ToolApproved, ToolCallPart, ToolDenied, UsageLimits

from .audit import LogfireAuditEmitter, build_audit_event, emit_audit_event
from .harness import LIMITS, HitlBudgetExceededError, HitlHarness, PendingResult
from .observability import enable_observability
from .store import SessionStore, UnknownSessionError

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Iterable

    from pydantic_ai import Agent, DeferredToolRequests, ModelMessage

    from .agent import HitlDeps
    from .audit import AuditEmitter

__all__ = ["create_app"]

# Fixed, content-free bodies (spec 013 R1.2): none of these echo a session
# id, a tool_call_id, or *why* a claim/check failed.
_UNKNOWN_SESSION_DETAIL = "session not found"
_PENDING_SET_VIOLATION_DETAIL = "decision does not match a pending tool call for this session"
_BUDGET_EXCEEDED_DETAIL = "usage budget exceeded"


class RunRequest(BaseModel):
    """Request body for ``POST /run``.

    ``extra="forbid"`` (spec 013 R4.1, R4.3): no ``message_history``,
    ``usage``, or ``model`` field is defined here, and any unknown field
    on the wire is a ``422`` rather than a silently-dropped extra key.
    """

    model_config = ConfigDict(extra="forbid")

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

    model_config = ConfigDict(extra="forbid")

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
    """Request body for ``POST /resume``.

    ``extra="forbid"`` (spec 013 R4.1, R4.3): no ``message_history``,
    ``usage``, or ``model`` field is defined here -- the resumed run's
    history and accumulated usage come exclusively from the server-side
    ``SessionStore`` (R4.2), never from the request body -- and any
    unknown field on the wire is a ``422`` rather than a silently-dropped
    extra key.

    ``decisions`` requires at least one entry (spec 013 R2.3): a request
    that resolves nothing has no valid outcome -- pydantic-ai itself
    raises ``UserError`` when a deferred run is resumed with no results
    for its pending calls -- so this is rejected at the schema boundary
    rather than surfacing as an unhandled 500.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str
    decisions: dict[str, Decision] = Field(min_length=1)


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


async def _handle_run(
    harness: HitlHarness, body: RunRequest
) -> CompletedResponse | PendingResponse:
    """Start a fresh agent run from ``body.prompt`` (R8.1, R8.2, spec 013 R2.4)."""
    try:
        result = await harness.start(body.prompt)
    except HitlBudgetExceededError as exc:
        raise HTTPException(status_code=429, detail=_BUDGET_EXCEEDED_DETAIL) from exc
    if isinstance(result, PendingResult):
        return _to_pending_response(result)
    return CompletedResponse(output=result.output)


def _tool_names_by_call_id(history: list[ModelMessage], call_ids: Iterable[str]) -> dict[str, str]:
    """Map each pending ``tool_call_id`` to its tool name by scanning the stored history.

    The last ``ModelResponse`` before a stop point carries the
    ``ToolCallPart``(s) a decision resolves; the store persists that full
    history but not a separate tool-name index, so this rebuilds the
    mapping on demand rather than widening ``SessionRecord``'s contract
    (spec 013 R3.1).
    """
    wanted = set(call_ids)
    names: dict[str, str] = {}
    for message in history:
        for part in message.parts:
            if isinstance(part, ToolCallPart) and part.tool_call_id in wanted:
                names[part.tool_call_id] = part.tool_name
    return names


async def _handle_resume(
    harness: HitlHarness, store: SessionStore, audit_emitter: AuditEmitter, body: ResumeRequest
) -> CompletedResponse | PendingResponse:
    """Resume ``body.session_id`` with the caller's decisions (R8.3, R8.5, spec 013 R1.2/R2/R3).

    The pending-set check (``409``) runs synchronously between ``claim()``
    and the ``await`` into the harness, so a concurrent claim on the same
    session can never observe a half-applied decision set (research.md
    AD-2, spec 013 R2.3). One audit event is emitted per decision -- at
    the point the decisions are about to be applied -- before that
    ``await``, so the audit trail records what was decided independently
    of whether the resumed run then completes, re-defers, or overruns its
    budget (spec 013 R3.1).
    """
    try:
        record = store.claim(body.session_id)
    except UnknownSessionError as exc:
        raise HTTPException(status_code=404, detail=_UNKNOWN_SESSION_DETAIL) from exc
    if not set(body.decisions.keys()) <= record.pending_call_ids:
        store.release(body.session_id)
        raise HTTPException(status_code=409, detail=_PENDING_SET_VIOLATION_DETAIL)
    tool_names = _tool_names_by_call_id(record.history, body.decisions.keys())
    for tool_call_id, decision in body.decisions.items():
        event = build_audit_event(
            session_id=body.session_id,
            tool_call_id=tool_call_id,
            tool_name=tool_names.get(tool_call_id, "unknown"),
            approved=decision.approved,
            override_args=decision.override_args,
            denial_message=decision.message,
        )
        emit_audit_event(audit_emitter, event)
    decisions = {
        tool_call_id: _to_deferred_result(decision)
        for tool_call_id, decision in body.decisions.items()
    }
    try:
        result = await harness.resume(body.session_id, decisions)
    except HitlBudgetExceededError as exc:
        raise HTTPException(status_code=429, detail=_BUDGET_EXCEEDED_DETAIL) from exc
    if isinstance(result, PendingResult):
        return _to_pending_response(result)
    return CompletedResponse(output=result.output)


def create_app(
    *,
    agent: Agent[HitlDeps, SupportOutput | DeferredToolRequests],
    store: SessionStore | None = None,
    usage_limits: UsageLimits = LIMITS,
    instrument: bool = True,
    audit_emitter: AuditEmitter | None = None,
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
        usage_limits: The budget enforced on every run this app drives;
            overridable so tests can inject a tight budget to make the
            ``429`` overrun path (spec 013 R2.4) deterministic.
        instrument: When ``True``, the lifespan calls
            :func:`patterns_hitl.observability.enable_observability`
            fail-soft on startup (R9.1). Tests other than
            ``test_observability.py`` pass ``False`` to skip it.
        audit_emitter: Where ``/resume`` sends one approval-decision audit
            event per decision (spec 013 R3); a fresh
            :class:`~patterns_hitl.audit.LogfireAuditEmitter` is created
            when omitted. Tests inject an in-memory emitter to assert on
            emitted events with zero real exporter I/O (R3.5).

    Returns:
        A FastAPI app exposing ``POST /run`` and ``POST /resume``.
    """
    resolved_store = store or SessionStore()
    resolved_audit_emitter = audit_emitter or LogfireAuditEmitter()
    harness = HitlHarness(agent, resolved_store, usage_limits=usage_limits)

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
        if instrument:
            enable_observability(app)
        yield

    app = FastAPI(lifespan=_lifespan)

    # Nested so each closes over the per-app `harness`/`resolved_store`; the
    # `@app.post` decorator registers it, which pyright cannot see through.
    # Each delegates its actual logic to a module-level helper (above) so
    # this factory's own cyclomatic complexity stays independent of the
    # HTTP status mapping the helpers implement.
    @app.post("/run")
    async def run(  # pyright: ignore[reportUnusedFunction]
        body: RunRequest,
    ) -> CompletedResponse | PendingResponse:
        return await _handle_run(harness, body)

    @app.post("/resume")
    async def resume(  # pyright: ignore[reportUnusedFunction]
        body: ResumeRequest,
    ) -> CompletedResponse | PendingResponse:
        return await _handle_resume(harness, resolved_store, resolved_audit_emitter, body)

    return app
