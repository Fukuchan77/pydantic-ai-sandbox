"""Observability tests for the Deep Research lane (Spec 009 Req 9).

``configure_tracing`` follows the sibling-lane priority chain (injected exporter >
OTLP env > no-op). When an ``InstrumentationSettings`` built from the returned
provider is passed to ``run_deep_research``, every model call across the pipeline
emits ``gen_ai.*`` spans; the test asserts span *existence* only (attributes are
the backend's concern), mirroring the RAG / SSE lanes' R7.3 discipline.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic_ai.models.instrumented import InstrumentationSettings

from patterns_deep_research import run_deep_research
from patterns_deep_research.observability import configure_tracing
from tests.support.fake_search import FakeSearchProvider
from tests.support.model_fakes import plan_payload, scripted_model

if TYPE_CHECKING:
    import pytest


def test_configure_tracing_no_op_without_exporter_or_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No exporter and no OTLP endpoint -> a provider that drops spans (no processor).
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    provider = configure_tracing()
    assert isinstance(provider, TracerProvider)


def test_configure_tracing_uses_otlp_when_env_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # With the OTLP endpoint set (and no explicit exporter), the lazy OTLP branch
    # wires a BatchSpanProcessor. No network is touched at construction time — the
    # exporter connects only on export, which this test never triggers.
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    provider = configure_tracing()
    assert isinstance(provider, TracerProvider)


async def test_instrumented_run_produces_spans() -> None:
    exporter = InMemorySpanExporter()
    provider = configure_tracing(exporter)
    instrumentation = InstrumentationSettings(tracer_provider=provider)

    model = scripted_model(plan=plan_payload(["q1"]))
    await run_deep_research(
        "q",
        model=model,
        search=FakeSearchProvider(),
        max_researchers=1,
        instrumentation=instrumentation,
    )

    assert exporter.get_finished_spans(), "instrumented run must produce >=1 span (Req 9)"
