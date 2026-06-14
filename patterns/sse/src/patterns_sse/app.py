"""FastAPI app and SSE delivery for the SSE lane (Spec 008-2c Req 3/4/6/7).

``create_app`` is the DI seam (ADR-2): it builds the FastAPI app with an
``EventSource`` injected, so the lane src stays framework-agnostic (NFR-3 /
R3.3) -- offline tests inject a scripted fake, the gated Ollama integration
injects a pydantic-ai ``run_stream_events`` adapter. The single endpoint
``POST /sse/runs`` drives that producer and streams each ``SseEvent`` over
``text/event-stream`` via sse-starlette's ``EventSourceResponse``.

The body generator owns the delivery invariants:

* it forwards events in source order ``step_started -> tool_called* -> token* ->
  completed`` (R4.1) -- the producer owns the ordering, the app preserves it;
* a run-time error becomes a terminal ``error`` event and is never silently
  swallowed (R4.3); ``completed`` / ``error`` always end the stream (R4.4);
* client disconnect surfaces as ``asyncio.CancelledError`` from sse-starlette's
  task group -- re-raised after cleanup, with the producer released in
  ``finally`` (R6.1/6.3). ``request.is_disconnected()`` is the cooperative
  active-break the clarifications adopted on top of that;
* one app span is opened per request from the injected ``tracer_provider``
  (R7.1, ADR-5); with no provider the span is a no-op.

A safety cap and a per-send timeout (R-2) keep a non-terminating or stalled
producer from wedging ``ASGITransport``, which buffers the whole finite stream
(ADR-4a).
"""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from patterns_contracts import ErrorEvent
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from patterns_sse.events import to_sse

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from contextlib import AbstractContextManager

    from opentelemetry.sdk.trace import TracerProvider

    from patterns_sse.events import EventSource

__all__ = ["create_app"]

# R-2 backstop: a producer that forgets its terminal marker must never hang
# ASGITransport (which buffers the whole finite stream, ADR-4a). Real runs end
# far below this via the contract's `completed` / `error` markers (R4.4).
_MAX_EVENTS = 1000

# R-2: bound a single `send` so a stalled client cannot wedge the body task.
_SEND_TIMEOUT_SECONDS = 60.0

_SPAN_NAME = "sse.stream"
_TRACER_NAME = "patterns_sse.app"


class RunRequest(BaseModel):
    """Request body for ``POST /sse/runs``."""

    query: str = Field(description="The query that drives the agent run.")


def _open_span(tracer_provider: TracerProvider | None) -> AbstractContextManager[object]:
    """Open one app span per request (R7.1, ADR-5); a no-op when no provider is injected."""
    if tracer_provider is None:
        return nullcontext()
    return tracer_provider.get_tracer(_TRACER_NAME).start_as_current_span(_SPAN_NAME)


async def _event_stream(
    request: Request,
    source: EventSource,
    query: str,
    tracer_provider: TracerProvider | None,
) -> AsyncIterator[dict[str, str]]:
    """Drive ``source`` and yield each event as sse-starlette ``ServerSentEvent`` kwargs.

    Order, termination, disconnect and span handling follow the module docstring.

    Args:
        request: The live request, polled for client disconnect (R6.1).
        source: The injected ``EventSource`` producing the run's events.
        query: The query forwarded to ``source.stream``.
        tracer_provider: Provider for the per-request span, or ``None`` for no-op.

    Yields:
        ``{"event": <type>, "data": <model_dump_json()>}`` for each ``SseEvent``.
    """
    agen = source.stream(query)
    try:
        with _open_span(tracer_provider):
            try:
                sent = 0
                async for event in agen:
                    if await request.is_disconnected():
                        break  # cooperative active-break on client disconnect (R6.1)
                    yield to_sse(event)
                    sent += 1
                    if sent >= _MAX_EVENTS:
                        break  # R-2 backstop against a non-terminating producer
            except asyncio.CancelledError:
                raise  # client went away mid-stream; never swallow it (R6.3)
            except Exception as exc:  # noqa: BLE001 - any run-time error must terminate the stream as `error`, not crash it (R4.3)
                yield to_sse(ErrorEvent(message=f"{type(exc).__name__}: {exc}"))
    finally:
        aclose = getattr(agen, "aclose", None)
        if aclose is not None:
            await aclose()  # release the producer generator (R6.1)


def create_app(
    *,
    event_source: EventSource,
    tracer_provider: TracerProvider | None = None,
) -> FastAPI:
    """Build the SSE FastAPI app with the event producer injected (DI seam, R3.3/NFR-3).

    Args:
        event_source: The producer driven per request (scripted fake offline, a
            pydantic-ai adapter in the gated integration).
        tracer_provider: Provider opening one span per request (R7.1); ``None``
            disables tracing.

    Returns:
        A FastAPI app exposing ``POST /sse/runs`` (body ``{"query": str}``) that
        streams the producer's events as ``text/event-stream``.
    """
    app = FastAPI()

    # Nested so it closes over the injected `event_source` / `tracer_provider`;
    # the `@app.post` decorator registers it, which pyright cannot see through.
    @app.post("/sse/runs")
    async def run_stream(  # pyright: ignore[reportUnusedFunction]
        body: RunRequest, request: Request
    ) -> EventSourceResponse:
        """Stream the injected producer's events for ``body.query`` (R3.1)."""
        return EventSourceResponse(
            _event_stream(request, event_source, body.query, tracer_provider),
            send_timeout=_SEND_TIMEOUT_SECONDS,
        )

    return app
