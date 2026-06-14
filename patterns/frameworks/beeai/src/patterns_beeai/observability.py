"""OTel tracing bootstrap for the BeeAI lane (Spec 005 Req 6.1).

``configure_tracing`` matches the other lanes (explicit exporter > OTLP
env > no-op). Span emission uses the documented fallback from plan §8
R-3: beeai-framework 0.1.x has no first-party OTel instrumentation API
this lane can rely on, so ``traced`` wraps a pattern coroutine in a
manual span. Tests assert span existence through this wrapper (Req 6.2).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from opentelemetry.sdk.trace.export import SpanExporter

__all__ = ["configure_tracing", "traced"]


def configure_tracing(exporter: SpanExporter | None = None) -> TracerProvider:
    """Build a ``TracerProvider`` (injected exporter > OTLP env > no-op)."""
    provider = TracerProvider()
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    elif os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    return provider


async def traced[T](
    provider: TracerProvider,
    span_name: str,
    awaitable: Awaitable[T],
) -> T:
    """Await ``awaitable`` inside a manual span on ``provider``.

    Manual-span fallback (plan §8 R-3): unlike the PydanticAI lane
    (per-model ``instrument_model``) and the LlamaIndex lane
    (OpenInference instrumentor), BeeAI runs are wrapped from the
    outside. Only pattern-level spans exist, which still satisfies the
    "spans exist" bar of Req 6.2; richer per-LLM-call spans await a
    stable upstream instrumentation API.
    """
    tracer = provider.get_tracer("patterns_beeai")
    with tracer.start_as_current_span(span_name):
        return await awaitable
