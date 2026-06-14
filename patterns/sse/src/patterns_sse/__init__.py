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
``parse_sse_events`` — is wired here in Task 4.3 once ``events.py`` and
``app.py`` exist. At the scaffold stage (Task 1) the package is import-only so
the smoke test can assert clean import and sibling-lane isolation.
"""

from __future__ import annotations
