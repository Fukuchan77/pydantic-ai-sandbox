"""Observability tests (Spec 005 Req 6.2): spans exist when instrumented."""

from __future__ import annotations

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from patterns_llamaindex.observability import (
    configure_tracing,
    instrument_llamaindex,
    uninstrument_llamaindex,
)
from patterns_llamaindex.routing import run_routing
from tests.support.fake_llm import ScriptedLLM


async def test_routing_emits_spans_into_injected_exporter() -> None:
    exporter = InMemorySpanExporter()
    provider = configure_tracing(exporter)
    instrumentor = instrument_llamaindex(provider)
    try:
        llm = ScriptedLLM(
            route_payload={"route": "general", "reasoning": "scripted"},
            text="hi",
        )
        await run_routing("hello", llm=llm)
    finally:
        # Instrumentation is process-global; detach so other tests run clean.
        uninstrument_llamaindex(instrumentor)

    spans = exporter.get_finished_spans()
    assert spans, "instrumented pattern run must emit at least one span"
    # Req 6.3: existence of leaf LLM spans only — token aggregation is the
    # backend's concern (double-counting trap, research.md R-5).
    assert any("llm" in span.name.lower() or "complete" in span.name.lower() for span in spans)


def test_configure_tracing_without_exporter_is_noop_provider() -> None:
    provider = configure_tracing()
    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("probe"):
        pass
