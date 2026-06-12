"""OTel tracing bootstrap for the PydanticAI lane (Spec 005 Req 6.1).

``configure_tracing`` returns a ``TracerProvider`` wired to exactly one of:

* the caller-injected exporter (tests pass ``InMemorySpanExporter``), or
* an OTLP/HTTP exporter when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set, or
* nothing (a no-op provider) — spans are created but dropped.

PydanticAI emits ``gen_ai.*`` spans natively once an
``InstrumentationSettings`` built from this provider is passed to the
pattern entrypoints; no logfire dependency is needed in this lane.
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
    """Build a ``TracerProvider`` for pattern runs.

    Args:
        exporter: Optional explicit exporter. Tests inject
            ``InMemorySpanExporter`` here so span assertions never need a
            collector (Req 6.2). When ``None``, the
            ``OTEL_EXPORTER_OTLP_ENDPOINT`` environment variable selects
            OTLP/HTTP export; with neither, the provider drops spans.

    Returns:
        A ``TracerProvider`` ready to hand to
        ``pydantic_ai.models.instrumented.InstrumentationSettings``.
    """
    provider = TracerProvider()
    if exporter is not None:
        # SimpleSpanProcessor keeps test assertions synchronous — finished
        # spans are visible the moment the pattern coroutine returns.
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    elif os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        # Imported lazily so offline environments never touch the OTLP stack.
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    return provider
