"""Observability tests (Spec 005 Req 6.2): spans exist when instrumented."""

from __future__ import annotations

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from patterns_beeai.observability import configure_tracing, traced
from patterns_beeai.routing import run_routing
from tests.support.fake_chat_model import ScriptedChatModel


async def test_routing_emits_spans_into_injected_exporter() -> None:
    exporter = InMemorySpanExporter()
    provider = configure_tracing(exporter)

    llm = ScriptedChatModel(
        route_payload={"route": "general", "reasoning": "scripted"},
        text="hi",
    )
    result = await traced(provider, "pattern.routing", run_routing("hello", llm=llm))
    assert result.answer == "hi"

    spans = exporter.get_finished_spans()
    assert spans, "instrumented pattern run must emit at least one span"
    assert any(span.name == "pattern.routing" for span in spans)


def test_configure_tracing_without_exporter_is_noop_provider() -> None:
    provider = configure_tracing()
    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("probe"):
        pass
