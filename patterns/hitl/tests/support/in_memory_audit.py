"""In-memory AuditEmitter for hermetic audit-trail tests (spec 013 R3.5).

Collects every emitted :class:`~patterns_hitl.audit.AuditEvent` in a plain
list -- zero real exporter I/O, so ``test_audit_trail.py`` can assert on
exactly which events a ``/resume`` call produced without ever touching
Logfire.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from patterns_hitl.audit import AuditEvent

__all__ = ["InMemoryAuditEmitter", "RaisingAuditEmitter"]


class InMemoryAuditEmitter:
    """Collects every emitted event, in order, for direct assertion."""

    def __init__(self) -> None:
        """Start with an empty event log."""
        self.events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> None:
        """Append ``event`` to :attr:`events`."""
        self.events.append(event)


class RaisingAuditEmitter:
    """An emitter that always fails -- exercises the fail-soft boundary (R3.4)."""

    def emit(self, event: AuditEvent) -> None:
        """Raise unconditionally; the caller must swallow this."""
        del event
        msg = "audit exporter unavailable"
        raise RuntimeError(msg)
