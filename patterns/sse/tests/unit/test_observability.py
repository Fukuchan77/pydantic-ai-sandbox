"""Observability wiring for the SSE lane (Spec 008-2c Req 7.1/7.2/7.3).

Two concerns, both fully offline:

* ``configure_tracing`` resolves exactly one span sink along the priority chain
  shared with the sibling lanes -- an injected exporter (tests) beats
  ``OTEL_EXPORTER_OTLP_ENDPOINT`` (deployments) beats a no-op provider (R7.1);
* an instrumented ``create_app`` run emits at least one app span (``sse.stream``)
  into an injected ``InMemorySpanExporter`` (R7.2). Per R7.3 the assertions stop
  at span *existence* -- attribute/token aggregation is the backend's concern.

The OTLP tiers are exercised without a collector: the lazily imported
``OTLPSpanExporter`` is swapped for a recorder that returns an in-memory exporter,
so the env-endpoint branch is proven to construct an exporter with zero network
I/O. ``_active_span_processor._span_processors`` is read to count registered
processors -- the public SDK exposes no other way to distinguish the no-op tier
(zero processors) from the env tier (one).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import opentelemetry.exporter.otlp.proto.http.trace_exporter as otlp_trace_exporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from patterns_sse import create_app
from patterns_sse.observability import configure_tracing
from tests.support.scripted_source import ScriptedEventSource

if TYPE_CHECKING:
    import pytest
    from fastapi import FastAPI
    from opentelemetry.sdk.trace import TracerProvider

_OTLP_ENDPOINT_ENV = "OTEL_EXPORTER_OTLP_ENDPOINT"
_OTLP_ENDPOINT_VALUE = "http://collector.invalid:4318"


class _OtlpRecorder:
    """Stands in for ``OTLPSpanExporter``: records construction, exports nowhere."""

    def __init__(self) -> None:
        self.built = 0

    def __call__(self, *args: object, **kwargs: object) -> InMemorySpanExporter:
        del args, kwargs  # the recorder ignores endpoint/header kwargs (offline)
        self.built += 1
        return InMemorySpanExporter()


def _processor_count(provider: TracerProvider) -> int:
    """Count span processors registered on ``provider`` (no public SDK accessor)."""
    active = provider._active_span_processor  # pyright: ignore[reportPrivateUsage]
    return len(active._span_processors)  # pyright: ignore[reportPrivateUsage]


async def _post_run(app: FastAPI, query: str) -> httpx.Response:
    """POST ``/sse/runs`` over ASGITransport and return the buffered response."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://sse") as client:
        return await client.post("/sse/runs", json={"query": query})


def test_injected_exporter_captures_emitted_spans(monkeypatch: pytest.MonkeyPatch) -> None:
    # Injected tier: an explicit exporter is wired synchronously and captures spans.
    monkeypatch.delenv(_OTLP_ENDPOINT_ENV, raising=False)
    exporter = InMemorySpanExporter()
    provider = configure_tracing(exporter)

    with provider.get_tracer("test").start_as_current_span("probe"):
        pass

    assert [span.name for span in exporter.get_finished_spans()] == ["probe"]


def test_injected_exporter_wins_over_otlp_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    # Priority: an injected exporter beats OTEL_EXPORTER_OTLP_ENDPOINT (R7.1).
    monkeypatch.setenv(_OTLP_ENDPOINT_ENV, _OTLP_ENDPOINT_VALUE)
    recorder = _OtlpRecorder()
    monkeypatch.setattr(otlp_trace_exporter, "OTLPSpanExporter", recorder)
    exporter = InMemorySpanExporter()

    provider = configure_tracing(exporter)

    with provider.get_tracer("test").start_as_current_span("probe"):
        pass
    assert recorder.built == 0, "env branch must be skipped when an exporter is injected"
    assert [span.name for span in exporter.get_finished_spans()] == ["probe"]


def test_otlp_endpoint_builds_exporter_when_none_injected(monkeypatch: pytest.MonkeyPatch) -> None:
    # Env tier: with no injected exporter, the endpoint env builds an OTLP exporter.
    monkeypatch.setenv(_OTLP_ENDPOINT_ENV, _OTLP_ENDPOINT_VALUE)
    recorder = _OtlpRecorder()
    monkeypatch.setattr(otlp_trace_exporter, "OTLPSpanExporter", recorder)

    provider = configure_tracing()
    try:
        assert recorder.built == 1, "endpoint set + no exporter must build an OTLP exporter"
        assert _processor_count(provider) == 1
    finally:
        provider.shutdown()  # join the batch worker thread (no spans -> no export)


def test_no_exporter_and_no_endpoint_is_noop_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    # No-op tier: neither injected nor env -> zero processors; emission never errors.
    monkeypatch.delenv(_OTLP_ENDPOINT_ENV, raising=False)
    provider = configure_tracing()

    assert _processor_count(provider) == 0
    with provider.get_tracer("test").start_as_current_span("probe"):
        pass


async def test_create_app_emits_app_span_into_injected_exporter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # R7.2/7.3: an instrumented run emits at least one app span; existence only.
    monkeypatch.delenv(_OTLP_ENDPOINT_ENV, raising=False)
    exporter = InMemorySpanExporter()
    provider = configure_tracing(exporter)
    app = create_app(event_source=ScriptedEventSource(), tracer_provider=provider)

    resp = await _post_run(app, "weather")

    assert resp.status_code == 200
    spans = exporter.get_finished_spans()
    assert spans, "an instrumented run must emit at least one span (R7.2)"
    # The per-request app span is `sse.stream`; assert presence, not attributes (R7.3).
    assert any(span.name == "sse.stream" for span in spans)
