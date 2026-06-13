"""Observability tests — LlamaIndex lane (Spec 005 Req 6.2, Spec 006-2a Req 9.2/9.3).

Every instrumented pattern run must emit at least one span into an injected
``InMemorySpanExporter``. The LlamaIndex lane has no manual-span wrapper; it uses
OpenInference's process-global instrumentor (Req 9.1): the test installs it,
runs the pattern, then detaches it in ``finally`` (process-global state must be
isolated between tests). The routing test (Spec 005) and the four new-pattern
tests (Spec 006-2a Task 9.3) share that assertion shape, asserting on the
existence of a leaf LLM span only. Token aggregation is the backend's concern
(Req 9.3), so the assertions stop at span existence — asserting on token sums
here would re-introduce the double-counting trap the design explicitly avoids.
"""

from __future__ import annotations

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from patterns_llamaindex.autonomous_agent import run_autonomous_agent
from patterns_llamaindex.evaluator_optimizer import run_evaluator_optimizer
from patterns_llamaindex.observability import (
    configure_tracing,
    instrument_llamaindex,
    uninstrument_llamaindex,
)
from patterns_llamaindex.parallelization import run_parallelization
from patterns_llamaindex.prompt_chaining import run_prompt_chain
from patterns_llamaindex.routing import run_routing
from tests.support.fake_llm import (
    FinalTurn,
    ScriptedLLM,
    TurnSequencedLLM,
    VerdictSequencedLLM,
)


def _approve_all(_tool: str, _args: str) -> bool:
    """Approve every request (autonomous-agent span test needs no gating)."""
    return True


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


async def test_prompt_chaining_emits_spans_into_injected_exporter() -> None:
    # Req 9.2: an instrumented chain run emits at least one span (LlamaIndex
    # process-global instrumentor, Req 9.1).
    exporter = InMemorySpanExporter()
    provider = configure_tracing(exporter)
    instrumentor = instrument_llamaindex(provider)
    try:
        # "alpha beta gamma" (3 words) clears the word-count gate so finalize runs.
        llm = ScriptedLLM(text="alpha beta gamma")
        result = await run_prompt_chain("hello", llm=llm)
    finally:
        # Instrumentation is process-global; detach so other tests run clean.
        uninstrument_llamaindex(instrumentor)

    assert result.final_output == "alpha beta gamma"
    spans = exporter.get_finished_spans()
    assert spans, "instrumented prompt-chaining run must emit at least one span"
    # Req 9.3: leaf LLM span existence only — token aggregation is backend's.
    assert any("llm" in span.name.lower() or "complete" in span.name.lower() for span in spans)


async def test_parallelization_emits_spans_into_injected_exporter() -> None:
    # Req 9.2: an instrumented fan-out emits at least one span (LlamaIndex
    # process-global instrumentor, Req 9.1).
    exporter = InMemorySpanExporter()
    provider = configure_tracing(exporter)
    instrumentor = instrument_llamaindex(provider)
    try:
        # ScriptedLLM returns the same text for every branch, so a 3-way vote is
        # unanimous; this isolates the span assertion from vote tallying.
        llm = ScriptedLLM(text="answer")
        result = await run_parallelization("hello", variant="voting", llm=llm, n=3)
    finally:
        # Instrumentation is process-global; detach so other tests run clean.
        uninstrument_llamaindex(instrumentor)

    assert result.aggregate == "answer"
    spans = exporter.get_finished_spans()
    assert spans, "instrumented parallelization run must emit at least one span"
    # Req 9.3: leaf LLM span existence only — token aggregation is backend's.
    assert any("llm" in span.name.lower() or "complete" in span.name.lower() for span in spans)


async def test_evaluator_optimizer_emits_spans_into_injected_exporter() -> None:
    # Req 9.2: an instrumented loop emits at least one span (LlamaIndex
    # process-global instrumentor, Req 9.1).
    exporter = InMemorySpanExporter()
    provider = configure_tracing(exporter)
    instrumentor = instrument_llamaindex(provider)
    try:
        llm = VerdictSequencedLLM(
            verdicts=[{"verdict": "pass", "feedback": "good"}],
            candidate="answer",
        )
        result = await run_evaluator_optimizer("hello", llm=llm, max_iterations=2)
    finally:
        # Instrumentation is process-global; detach so other tests run clean.
        uninstrument_llamaindex(instrumentor)

    assert result.stop_reason == "passed"
    spans = exporter.get_finished_spans()
    assert spans, "instrumented evaluator-optimizer run must emit at least one span"
    # Req 9.3: leaf LLM span existence only — token aggregation is backend's.
    assert any("llm" in span.name.lower() or "complete" in span.name.lower() for span in spans)


async def test_autonomous_agent_emits_spans_into_injected_exporter() -> None:
    # Req 9.2: an instrumented tool loop emits at least one span (LlamaIndex
    # process-global instrumentor, Req 9.1).
    exporter = InMemorySpanExporter()
    provider = configure_tracing(exporter)
    instrumentor = instrument_llamaindex(provider)
    try:
        llm = TurnSequencedLLM([FinalTurn(text="done", tokens=1)])
        result = await run_autonomous_agent(
            "hello",
            llm=llm,
            max_iterations=2,
            allowed_tools=[],
            approval_hook=_approve_all,
            budget=10,
        )
    finally:
        # Instrumentation is process-global; detach so other tests run clean.
        uninstrument_llamaindex(instrumentor)

    assert result.stop_reason == "completed"
    spans = exporter.get_finished_spans()
    assert spans, "instrumented autonomous-agent run must emit at least one span"
    # Req 9.3: leaf LLM span existence only — token aggregation is backend's.
    assert any("llm" in span.name.lower() or "complete" in span.name.lower() for span in spans)


def test_configure_tracing_without_exporter_is_noop_provider() -> None:
    provider = configure_tracing()
    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("probe"):
        pass
