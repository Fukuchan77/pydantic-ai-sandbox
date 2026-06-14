"""OTel tracing bootstrap for the SSE lane (Spec 008-2c Req 7.1).

``configure_tracing`` returns a ``TracerProvider`` wired to exactly one of:

* the caller-injected exporter (tests pass ``InMemorySpanExporter``), or
* an OTLP/HTTP exporter when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set, or
* nothing (a no-op provider) -- spans are created but dropped.

Owned by this lane rather than imported from a sibling: the cross-framework
discipline (NFR-3) is that each lane copies the observability seam (ADR-5). The
priority chain is identical to the pydantic-ai / RAG lanes, but this lane has no
framework instrumentor -- ``app.py`` opens its own per-request ``sse.stream``
span from the provider this function returns. This module owns only the wiring:
it neither emits spans nor aggregates span attributes (the backend's concern,
R7.3).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor

if TYPE_CHECKING:
    from opentelemetry.sdk.trace.export import SpanExporter

__all__ = ["configure_tracing"]


def configure_tracing(exporter: SpanExporter | None = None) -> TracerProvider:
    """Build a ``TracerProvider`` for SSE-lane runs (injected > OTLP env > no-op).

    Args:
        exporter: Optional explicit exporter. Tests inject
            ``InMemorySpanExporter`` here so span assertions never need a
            collector (R7.2). When ``None``, the ``OTEL_EXPORTER_OTLP_ENDPOINT``
            environment variable selects OTLP/HTTP export; with neither, the
            provider drops spans.

    Returns:
        A ``TracerProvider`` ready to hand to ``create_app(tracer_provider=...)``.
    """
    provider = TracerProvider()
    if exporter is not None:
        # SimpleSpanProcessor keeps test assertions synchronous -- finished spans
        # are visible the moment the streamed run's span ends.
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    elif os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        # Imported lazily so offline environments never touch the OTLP stack.
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    return provider
