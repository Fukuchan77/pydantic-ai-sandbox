"""Observability tests — RAG lane (Spec 007-2b Req 8.1, 8.2, 8.3).

Two contracts, mirroring the sibling ``llamaindex`` lane (NFR-3 lane self-copy):

* ``configure_tracing`` resolves an exporter by a fixed priority chain
  (injected exporter > ``OTEL_EXPORTER_OTLP_ENDPOINT`` > no-op) and
  ``instrument_llamaindex`` / ``uninstrument_llamaindex`` attach and detach the
  process-global OpenInference instrumentor (Req 8.1). The priority tests pin
  each rung of the chain, and the round-trip test proves a detached instrumentor
  emits no further spans (process-global state must be isolated).
* An instrumented ``run_rag`` emits at least one span into an injected
  ``InMemorySpanExporter`` (Req 8.2), and the assertions stop at the *existence*
  of a leaf LLM span and a leaf retrieval span (Req 8.3). Token aggregation is
  the backend's concern, so this suite never sums span attributes — that would
  re-introduce the double-counting trap the design explicitly avoids.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from patterns_contracts import RagAnswer

from patterns_rag.chunking import ChunkRecord
from patterns_rag.indexing import build_index
from patterns_rag.observability import (
    configure_tracing,
    instrument_llamaindex,
    uninstrument_llamaindex,
)
from patterns_rag.rag import run_rag
from tests.support.fake_embedding import HashEmbedding
from tests.support.fake_llm import ScriptedLLM

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import ClassVar

    from opentelemetry.sdk.trace import ReadableSpan

_OTLP_MODULE = "opentelemetry.exporter.otlp.proto.http.trace_exporter"


class _RecordingOTLPExporter(SpanExporter):
    """A real (no-op) ``SpanExporter`` that records each construction.

    Stands in for the real ``OTLPSpanExporter`` so a test can prove the OTLP
    branch fired (env set, no injected exporter) without opening a network
    connection: it satisfies ``BatchSpanProcessor`` yet exports nothing.
    """

    constructions: ClassVar[list[_RecordingOTLPExporter]] = []

    def __init__(self) -> None:
        _RecordingOTLPExporter.constructions.append(self)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        del spans
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None


def _patch_otlp(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the real OTLP exporter with the recording spy and reset its log."""
    _RecordingOTLPExporter.constructions.clear()
    otlp_mod = pytest.importorskip(_OTLP_MODULE)
    monkeypatch.setattr(otlp_mod, "OTLPSpanExporter", _RecordingOTLPExporter)


def _chunks() -> list[ChunkRecord]:
    """Two deterministic chunk records for an index-backed RAG run."""
    return [
        ChunkRecord(
            chunk_id="doc::0000", source="doc", locator="page=1", text="alpha grounding body"
        ),
        ChunkRecord(
            chunk_id="doc::0001", source="doc", locator="page=2", text="beta grounding body"
        ),
    ]


# --- Req 8.1: exporter priority chain --------------------------------------


def test_configure_tracing_without_exporter_or_endpoint_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No injected exporter and no OTLP endpoint -> a working but exporter-less
    # provider; the OTLP branch must not fire (no spy construction).
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    _patch_otlp(monkeypatch)

    provider = configure_tracing()

    assert isinstance(provider, TracerProvider)
    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("probe"):
        pass
    assert not _RecordingOTLPExporter.constructions, "no-op path must not build an OTLP exporter"


def test_configure_tracing_prefers_injected_exporter_over_otlp_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Injection wins even when the OTLP endpoint is set: spans land in the
    # injected exporter and the OTLP branch is short-circuited (Req 8.1).
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    _patch_otlp(monkeypatch)

    exporter = InMemorySpanExporter()
    provider = configure_tracing(exporter)
    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("probe"):
        pass

    assert exporter.get_finished_spans(), "injected exporter must receive the span"
    assert not _RecordingOTLPExporter.constructions, "injection must short-circuit the OTLP branch"


def test_configure_tracing_falls_back_to_otlp_when_endpoint_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Endpoint set, no injected exporter -> the OTLP exporter is constructed
    # (env > no-op rung of the chain, Req 8.1).
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    _patch_otlp(monkeypatch)

    provider = configure_tracing()

    assert isinstance(provider, TracerProvider)
    assert _RecordingOTLPExporter.constructions, (
        "endpoint set + no exporter must build the OTLP path"
    )
    provider.shutdown()  # join the BatchSpanProcessor worker thread (no spans, no network)


# --- Req 8.2 / 8.3: span emission during an instrumented RAG run -----------


async def test_instrumented_run_rag_emits_leaf_llm_and_retrieval_spans() -> None:
    # An instrumented end-to-end run emits >= 1 span, including a leaf LLM span
    # and a leaf retrieval span (Req 8.2/8.3). Build the index *after* attaching
    # the process-global instrumentor so the whole pipeline is observed.
    exporter = InMemorySpanExporter()
    provider = configure_tracing(exporter)
    instrumentor = instrument_llamaindex(provider)
    try:
        index = build_index(_chunks(), embed_model=HashEmbedding())
        retriever = index.as_retriever(similarity_top_k=2)
        result = await run_rag("alpha?", llm=ScriptedLLM(answer="A"), retriever=retriever, top_k=2)
    finally:
        # Instrumentation is process-global; detach so other tests run clean.
        uninstrument_llamaindex(instrumentor)

    assert isinstance(result, RagAnswer)
    spans = exporter.get_finished_spans()
    assert spans, "an instrumented RAG run must emit at least one span (Req 8.2)"
    names = [span.name.lower() for span in spans]
    # Req 8.3: existence only — token aggregation is the backend's concern.
    assert any("llm" in name or "complete" in name for name in names), names
    assert any("retriev" in name for name in names), names


async def test_uninstrument_stops_further_span_emission() -> None:
    # After detaching the process-global instrumentor, a later run feeds no new
    # spans into the same exporter (Req 8.1 attach/detach is real, not cosmetic).
    index = build_index(_chunks(), embed_model=HashEmbedding())
    retriever = index.as_retriever(similarity_top_k=2)

    exporter = InMemorySpanExporter()
    provider = configure_tracing(exporter)
    instrumentor = instrument_llamaindex(provider)
    try:
        await run_rag("q", llm=ScriptedLLM(), retriever=retriever, top_k=2)
    finally:
        uninstrument_llamaindex(instrumentor)
    instrumented_count = len(exporter.get_finished_spans())
    assert instrumented_count, "the instrumented run must emit spans"

    await run_rag("q", llm=ScriptedLLM(), retriever=retriever, top_k=2)

    assert len(exporter.get_finished_spans()) == instrumented_count, (
        "a detached instrumentor must not emit further spans"
    )
