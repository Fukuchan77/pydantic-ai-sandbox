"""SSE serialization helpers and the ``EventSource`` DI seam (Spec 008-2c Req 2.3, 4.2).

ADR-3 fixes the wire mapping in both directions and concentrates it in one place
so the discriminator stays the single source of truth:

* :func:`to_sse` maps an :data:`~patterns_contracts.SseEvent` to its sse-starlette
  ``ServerSentEvent`` kwargs -- ``event:`` is the ``type`` discriminator, ``data:``
  is the member's ``model_dump_json()`` (Req 2.3). No hand-rolled newline-delimited
  ``event:`` / ``data:`` formatting (which would risk SSE-framing edge cases).
* :func:`parse_sse_events` reverses a ``text/event-stream`` body: it pulls each
  ``data:`` line and validates it through ``TypeAdapter(SseEvent).validate_json``,
  letting the ``type`` discriminator dispatch back to the exact contract member
  (Req 4.2). It deliberately does **not** branch on ``event:`` -- the ``data:``
  JSON is authoritative, and non-``data:`` framing (keepalive ``:`` comments,
  ``event:`` / ``id:`` / ``retry:`` lines) is ignored.

The lane src stays framework-agnostic (Req 1.3 / NFR-3): this module imports only
the shared contract union via the ``patterns_contracts`` path dependency and the
:class:`~typing.Protocol` seam through which the FastAPI app receives whatever
produces the events (a scripted fake offline, a pydantic-ai adapter in the gated
Ollama integration). It never imports a sibling lane.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from patterns_contracts import SseEvent
from pydantic import TypeAdapter

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

__all__ = ["EventSource", "parse_sse_events", "to_sse"]

# Built once at import time: TypeAdapter compilation is non-trivial, and the
# discriminated union is immutable, so the adapter is shared across calls.
_SSE_EVENT_ADAPTER: TypeAdapter[SseEvent] = TypeAdapter(SseEvent)

# SSE field prefix the reverse mapping consumes. The contract's `model_dump_json`
# emits single-line JSON, so one `data:` line carries one whole event.
_DATA_PREFIX = "data:"


@runtime_checkable
class EventSource(Protocol):
    """The DI seam that feeds the SSE app one agent run's events (Req 1.3 / NFR-3).

    Declared as a plain (non-``async``) method returning an ``AsyncIterator`` so
    that an ``async def stream(...)`` async-generator implementation is a
    structural match; an ``async def`` declaration here would instead type the
    member as a coroutine *returning* an iterator, which no generator satisfies.

    Concurrency: one ``EventSource`` is injected for the app's lifetime and
    ``create_app`` calls ``stream`` once per request, so an implementation MUST
    return an independent async generator per call and hold no per-stream state on
    ``self`` that concurrent requests would race (the pydantic-ai adapter is safe
    because ``run_stream_events`` opens a fresh run each call).
    """

    def stream(self, query: str) -> AsyncIterator[SseEvent]:
        """Yield the ordered event sequence for ``query`` (step -> tool* -> token* -> end)."""
        ...


def to_sse(event: SseEvent) -> dict[str, str]:
    """Map an ``SseEvent`` to sse-starlette ``ServerSentEvent`` kwargs (ADR-3, Req 2.3).

    Args:
        event: The contract event to put on the wire.

    Returns:
        ``{"event": <type discriminator>, "data": <model_dump_json()>}`` -- the
        ``event:`` name is the member's ``type``; the ``data:`` payload is its
        JSON serialization.
    """
    return {"event": event.type, "data": event.model_dump_json()}


def parse_sse_events(body: str) -> list[SseEvent]:
    """Reverse a ``text/event-stream`` body to the typed event list (ADR-3, Req 4.2).

    Each ``data:`` line is validated through ``TypeAdapter(SseEvent).validate_json``;
    the ``type`` discriminator dispatches it back to the exact contract member.
    Non-``data:`` lines (keepalive ``:`` comments, ``event:`` / ``id:`` / ``retry:``
    framing, blank separators) are ignored -- the JSON payload is authoritative.

    Args:
        body: The buffered ``text/event-stream`` response body.

    Returns:
        The events in wire order, each a concrete member of the ``SseEvent`` union.
    """
    events: list[SseEvent] = []
    for line in body.splitlines():
        if line.startswith(_DATA_PREFIX):
            payload = line[len(_DATA_PREFIX) :].strip()
            events.append(_SSE_EVENT_ADAPTER.validate_json(payload))
    return events
