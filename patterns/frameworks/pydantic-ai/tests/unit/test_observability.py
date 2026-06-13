"""Observability tests (Spec 005 Req 6.2, Spec 006-2a Req 9.2/9.3).

Every instrumented pattern run must emit at least one leaf ``gen_ai`` span into
an injected ``InMemorySpanExporter``. The routing test (Spec 005) and the four
new-pattern tests (Spec 006-2a Task 9.1) share that single assertion shape.
Token aggregation is the backend's concern (Req 9.3), so the assertions stop at
span existence — asserting on token sums here would re-introduce the
double-counting trap the design explicitly avoids.
"""

from __future__ import annotations

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic_ai.models.instrumented import InstrumentationSettings

from patterns_pydantic_ai.autonomous_agent import run_autonomous_agent
from patterns_pydantic_ai.evaluator_optimizer import run_evaluator_optimizer
from patterns_pydantic_ai.observability import configure_tracing
from patterns_pydantic_ai.parallelization import run_parallelization
from patterns_pydantic_ai.prompt_chaining import run_prompt_chain
from patterns_pydantic_ai.routing import run_routing
from tests.support.model_fakes import (
    FinalTurn,
    scripted_model,
    turn_sequenced_model,
    verdict_sequenced_model,
    voting_model,
)


def _approve_all(_tool: str, _args: str) -> bool:
    """Approve every request (autonomous-agent span test needs no gating)."""
    return True


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


async def test_prompt_chaining_emits_spans_into_injected_exporter() -> None:
    # Req 9.2: an instrumented chain run emits at least one (leaf gen_ai) span.
    exporter = InMemorySpanExporter()
    provider = configure_tracing(exporter)
    settings = InstrumentationSettings(tracer_provider=provider)
    # "alpha beta gamma" (3 words) clears the word-count gate so finalize runs.
    model = scripted_model(text="alpha beta gamma")

    await run_prompt_chain("hello", model=model, instrumentation=settings)

    spans = exporter.get_finished_spans()
    assert spans, "instrumented prompt-chaining run must emit at least one span"
    # Req 9.3: leaf LLM spans only — token aggregation is the backend's concern.
    assert any("gen_ai" in str(span.attributes) for span in spans)


async def test_parallelization_emits_spans_into_injected_exporter() -> None:
    # Req 9.2: an instrumented fan-out emits at least one (leaf gen_ai) span.
    exporter = InMemorySpanExporter()
    provider = configure_tracing(exporter)
    settings = InstrumentationSettings(tracer_provider=provider)
    model = voting_model(["x", "x", "y"])

    await run_parallelization("hello", variant="voting", model=model, n=3, instrumentation=settings)

    spans = exporter.get_finished_spans()
    assert spans, "instrumented parallelization run must emit at least one span"
    # Req 9.3: leaf LLM spans only — token aggregation is the backend's concern.
    assert any("gen_ai" in str(span.attributes) for span in spans)


async def test_evaluator_optimizer_emits_spans_into_injected_exporter() -> None:
    # Req 9.2: an instrumented loop emits at least one (leaf gen_ai) span.
    exporter = InMemorySpanExporter()
    provider = configure_tracing(exporter)
    settings = InstrumentationSettings(tracer_provider=provider)
    model = verdict_sequenced_model(
        verdicts=[{"verdict": "pass", "feedback": "good"}],
        candidate="answer",
    )

    await run_evaluator_optimizer("hello", model=model, max_iterations=2, instrumentation=settings)

    spans = exporter.get_finished_spans()
    assert spans, "instrumented evaluator-optimizer run must emit at least one span"
    # Req 9.3: leaf LLM spans only — token aggregation is the backend's concern.
    assert any("gen_ai" in str(span.attributes) for span in spans)


async def test_autonomous_agent_emits_spans_into_injected_exporter() -> None:
    # Req 9.2: an instrumented tool loop emits at least one (leaf gen_ai) span.
    exporter = InMemorySpanExporter()
    provider = configure_tracing(exporter)
    settings = InstrumentationSettings(tracer_provider=provider)
    model = turn_sequenced_model([FinalTurn(text="done", tokens=1)])

    await run_autonomous_agent(
        "hello",
        model=model,
        max_iterations=2,
        allowed_tools=[],
        approval_hook=_approve_all,
        budget=10,
        instrumentation=settings,
    )

    spans = exporter.get_finished_spans()
    assert spans, "instrumented autonomous-agent run must emit at least one span"
    # Req 9.3: leaf LLM spans only — token aggregation is the backend's concern.
    assert any("gen_ai" in str(span.attributes) for span in spans)


def test_configure_tracing_without_exporter_is_noop_provider() -> None:
    provider = configure_tracing()
    # No processors registered (no exporter injected, no OTLP endpoint set):
    # span emission is a no-op rather than an error.
    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("probe"):
        pass
