"""Structured approval audit trail for the HITL lane (spec 013 R3, research.md AD-3).

One :class:`AuditEvent` per approval decision applied on ``/resume``
(app.py) -- what was decided, never what the tool's raw arguments were.
:func:`build_audit_event` is the single point where a caller's
``approved``/``override_args``/``denial_message`` collapse into that
masked shape (R3.2, R3.3); :func:`emit_audit_event` is the single fail-soft
boundary an injected :class:`AuditEmitter` runs behind (R3.4), so a broken
or unconfigured exporter -- Logfire's default or a caller-supplied one --
never blocks or fails the resume it is merely observing.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, Protocol

import logfire
from pydantic import BaseModel

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "AuditEmitter",
    "AuditEvent",
    "LogfireAuditEmitter",
    "build_audit_event",
    "emit_audit_event",
]

DecisionKind = Literal["approved", "approved_with_override", "denied"]


class AuditEvent(BaseModel):
    """One approval decision, minus any raw tool-argument values (R3.2, R3.3).

    Attributes:
        session_id: The session the decision was applied under.
        tool_call_id: The pending tool call the decision resolves.
        tool_name: The tool the decision applies to.
        decision: What the caller decided.
        denial_message: The caller's reason, when ``decision`` is
            ``"denied"``; ``None`` otherwise.
        overridden_keys: The argument key set an ``approved_with_override``
            decision replaced -- never the values themselves (R3.2, R3.3).
        timestamp: When this event was built.
    """

    session_id: str
    tool_call_id: str
    tool_name: str
    decision: DecisionKind
    denial_message: str | None = None
    overridden_keys: tuple[str, ...] = ()
    timestamp: datetime


class AuditEmitter(Protocol):
    """Injectable sink for :class:`AuditEvent` (plan.md AuditTrail, mirrors observability.py's seam)."""

    def emit(self, event: AuditEvent) -> None:
        """Record one audit event."""
        ...


class LogfireAuditEmitter:
    """Default :class:`AuditEmitter`: one structured Logfire log entry per decision."""

    def emit(self, event: AuditEvent) -> None:
        """Log ``event`` via Logfire.

        Any failure here is handled by the caller
        (:func:`emit_audit_event`), not swallowed locally -- the fail-soft
        boundary is centralized so it covers every emitter, not just this
        one.
        """
        logfire.info("hitl.audit.decision", **event.model_dump(mode="json"))


def build_audit_event(
    *,
    session_id: str,
    tool_call_id: str,
    tool_name: str,
    approved: bool,
    override_args: Mapping[str, object] | None = None,
    denial_message: str | None = None,
) -> AuditEvent:
    """Map one caller decision onto an :class:`AuditEvent`, masking any override values.

    Args:
        session_id: The session the decision was applied under.
        tool_call_id: The pending tool call the decision resolves.
        tool_name: The tool the decision applies to.
        approved: Whether the caller approved (vs. denied) the tool call.
        override_args: The caller-supplied argument overrides, when
            ``approved`` is ``True``; only their key set is recorded
            (R3.2, R3.3). Ignored when ``approved`` is ``False``.
        denial_message: The caller's reason, when ``approved`` is
            ``False``. Ignored when ``approved`` is ``True``.

    Returns:
        The resulting :class:`AuditEvent`, timestamped now.
    """
    if not approved:
        return AuditEvent(
            session_id=session_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            decision="denied",
            denial_message=denial_message,
            timestamp=datetime.now(UTC),
        )
    if override_args:
        return AuditEvent(
            session_id=session_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            decision="approved_with_override",
            overridden_keys=tuple(override_args.keys()),
            timestamp=datetime.now(UTC),
        )
    return AuditEvent(
        session_id=session_id,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        decision="approved",
        timestamp=datetime.now(UTC),
    )


def emit_audit_event(emitter: AuditEmitter, event: AuditEvent) -> None:
    """Emit ``event`` through ``emitter``, swallowing any failure (R3.4).

    Centralizing the fail-soft boundary here -- rather than inside every
    :class:`AuditEmitter` implementation -- means an unconfigured Logfire
    install *and* a broken caller-supplied emitter both leave ``/resume``
    unaffected; only this one call site needs the broad except.

    Args:
        emitter: The sink to record ``event`` through.
        event: The event to record.
    """
    # Fail-soft boundary (R3.4): an emitter failure must never fail the resume;
    # there is no lane-owned logger to report it to that would not risk the
    # same failure mode as the emitter it is reporting on.
    with contextlib.suppress(Exception):
        emitter.emit(event)
