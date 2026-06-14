"""Server-Sent Events delivery lane of the cross-framework patterns (Spec 008-2c).

This package delivers agent-run events to clients over ``text/event-stream``: a
FastAPI endpoint drives an injected ``EventSource`` and streams each
``SseEvent`` (the discriminated union owned by ``patterns_contracts``) through
sse-starlette's ``EventSourceResponse``.

The lane src is **framework-agnostic** (Req 1.3 / NFR-3): it owns delivery and
the ``EventSource`` DI seam, never a sibling lane. Offline tests inject a
scripted fake; the gated Ollama integration injects a pydantic-ai
``run_stream_events`` adapter.

The flattened public surface — ``create_app`` / ``EventSource`` / ``to_sse`` /
``parse_sse_events`` — is re-exported here (Task 4.3): callers import the lane's
delivery entry point and serialization helpers from the package root, while the
lane src stays framework-agnostic (it receives its producer only through the
``EventSource`` DI seam, R1.3 / NFR-3).
"""

from __future__ import annotations

from patterns_sse.app import create_app
from patterns_sse.events import EventSource, parse_sse_events, to_sse

__all__ = ["EventSource", "create_app", "parse_sse_events", "to_sse"]
