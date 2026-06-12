"""OTel tracing bootstrap for the LlamaIndex lane (Spec 005 Req 6.1).

Two pieces:

* ``configure_tracing`` — identical contract to the other lanes: explicit
  exporter (tests) > ``OTEL_EXPORTER_OTLP_ENDPOINT`` (deployments) > no-op.
* ``instrument_llamaindex`` / ``uninstrument_llamaindex`` — OpenInference's
  ``LlamaIndexInstrumentor`` hooks LlamaIndex's instrumentation dispatcher
  into the given provider. Instrumentation is process-global (unlike the
  PydanticAI lane's per-model wrapping), hence the explicit un-instrument
  for test isolation.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from openinference.instrumentation.llama_index import LlamaIndexInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor

if TYPE_CHECKING:
    from opentelemetry.sdk.trace.export import SpanExporter

__all__ = ["configure_tracing", "instrument_llamaindex", "uninstrument_llamaindex"]


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


def instrument_llamaindex(provider: TracerProvider) -> LlamaIndexInstrumentor:
    """Route LlamaIndex spans into ``provider`` (process-global)."""
    instrumentor = LlamaIndexInstrumentor()
    instrumentor.instrument(tracer_provider=provider)
    return instrumentor


def uninstrument_llamaindex(instrumentor: LlamaIndexInstrumentor) -> None:
    """Detach a previously installed instrumentor (test isolation)."""
    instrumentor.uninstrument()
