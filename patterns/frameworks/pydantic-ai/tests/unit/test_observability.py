"""Observability tests (Spec 005 Req 6.2): spans exist when instrumented."""

from __future__ import annotations

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic_ai.models.instrumented import InstrumentationSettings

from patterns_pydantic_ai.observability import configure_tracing
from patterns_pydantic_ai.routing import run_routing
from tests.support.model_fakes import scripted_model


async def test_routing_emits_spans_into_injected_exporter() -> None:
    exporter = InMemorySpanExporter()
    provider = configure_tracing(exporter)
    settings = InstrumentationSettings(tracer_provider=provider)

    model = scripted_model(
        route_payload={"route": "general", "reasoning": "scripted"},
        text="hi",
    )
    await run_routing("hello", model=model, instrumentation=settings)

    spans = exporter.get_finished_spans()
    assert spans, "instrumented pattern run must emit at least one span"
    # Req 6.3: assert only that leaf LLM spans exist — aggregation across
    # parent spans is the backend's concern (token double-counting trap).
    assert any("gen_ai" in str(span.attributes) for span in spans)


def test_configure_tracing_without_exporter_is_noop_provider() -> None:
    provider = configure_tracing()
    # No processors registered (no exporter injected, no OTLP endpoint set):
    # span emission is a no-op rather than an error.
    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("probe"):
        pass
