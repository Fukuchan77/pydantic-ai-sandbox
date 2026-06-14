"""Observability tests — BeeAI lane (Spec 005 Req 6.2, Spec 006-2a Req 9.2/9.3).

Every instrumented pattern run must emit at least one span into an injected
``InMemorySpanExporter``. The BeeAI lane has no first-party OTel instrumentation
API, so spans come from the manual-span fallback (Req 9.1): the caller wraps a
pattern coroutine in :func:`patterns_beeai.observability.traced`, which opens a
single ``pattern.<name>`` span. The routing test (Spec 005) and the four
new-pattern tests (Spec 006-2a Task 9.2) share that assertion shape. Token
aggregation is the backend's concern (Req 9.3), so the assertions stop at span
existence — asserting on token sums here would re-introduce the double-counting
trap the design explicitly avoids.
"""

from __future__ import annotations

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from patterns_beeai.autonomous_agent import run_autonomous_agent
from patterns_beeai.evaluator_optimizer import run_evaluator_optimizer
from patterns_beeai.observability import configure_tracing, traced
from patterns_beeai.parallelization import run_parallelization
from patterns_beeai.prompt_chaining import run_prompt_chain
from patterns_beeai.routing import run_routing
from tests.support.fake_chat_model import (
    FinalTurn,
    ScriptedChatModel,
    TurnSequencedChatModel,
    VerdictSequencedChatModel,
    VotingChatModel,
)


def _approve_all(_tool: str, _args: str) -> bool:
    """Approve every request (autonomous-agent span test needs no gating)."""
    return True


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


async def test_prompt_chaining_emits_spans_into_injected_exporter() -> None:
    # Req 9.2: an instrumented chain run emits at least one span. The BeeAI lane
    # uses the manual-span fallback (Req 9.1), so the caller wraps run in traced.
    exporter = InMemorySpanExporter()
    provider = configure_tracing(exporter)
    # "alpha beta gamma" (3 words) clears the word-count gate so finalize runs.
    llm = ScriptedChatModel(text="alpha beta gamma")

    result = await traced(
        provider,
        "pattern.prompt_chaining",
        run_prompt_chain("hello", llm=llm),
    )

    assert result.final_output == "alpha beta gamma"
    spans = exporter.get_finished_spans()
    assert spans, "instrumented prompt-chaining run must emit at least one span"
    # Req 9.3: pattern-level span existence only — token aggregation is backend's.
    assert any(span.name == "pattern.prompt_chaining" for span in spans)


async def test_parallelization_emits_spans_into_injected_exporter() -> None:
    # Req 9.2: an instrumented fan-out emits at least one span (manual-span
    # fallback, Req 9.1 — the caller wraps the run in traced).
    exporter = InMemorySpanExporter()
    provider = configure_tracing(exporter)
    llm = VotingChatModel(["x", "x", "y"])

    result = await traced(
        provider,
        "pattern.parallelization",
        run_parallelization("hello", variant="voting", llm=llm, n=3),
    )

    assert result.aggregate == "x"
    spans = exporter.get_finished_spans()
    assert spans, "instrumented parallelization run must emit at least one span"
    # Req 9.3: pattern-level span existence only — token aggregation is backend's.
    assert any(span.name == "pattern.parallelization" for span in spans)


async def test_evaluator_optimizer_emits_spans_into_injected_exporter() -> None:
    # Req 9.2: an instrumented loop emits at least one span (manual-span
    # fallback, Req 9.1 — the caller wraps the run in traced).
    exporter = InMemorySpanExporter()
    provider = configure_tracing(exporter)
    llm = VerdictSequencedChatModel(
        verdicts=[{"verdict": "pass", "feedback": "good"}],
        candidate="answer",
    )

    result = await traced(
        provider,
        "pattern.evaluator_optimizer",
        run_evaluator_optimizer("hello", llm=llm, max_iterations=2),
    )

    assert result.stop_reason == "passed"
    spans = exporter.get_finished_spans()
    assert spans, "instrumented evaluator-optimizer run must emit at least one span"
    # Req 9.3: pattern-level span existence only — token aggregation is backend's.
    assert any(span.name == "pattern.evaluator_optimizer" for span in spans)


async def test_autonomous_agent_emits_spans_into_injected_exporter() -> None:
    # Req 9.2: an instrumented tool loop emits at least one span (manual-span
    # fallback, Req 9.1 — the caller wraps the run in traced).
    exporter = InMemorySpanExporter()
    provider = configure_tracing(exporter)
    llm = TurnSequencedChatModel([FinalTurn(text="done", tokens=1)])

    result = await traced(
        provider,
        "pattern.autonomous_agent",
        run_autonomous_agent(
            "hello",
            llm=llm,
            max_iterations=2,
            allowed_tools=[],
            approval_hook=_approve_all,
            budget=10,
        ),
    )

    assert result.stop_reason == "completed"
    spans = exporter.get_finished_spans()
    assert spans, "instrumented autonomous-agent run must emit at least one span"
    # Req 9.3: pattern-level span existence only — token aggregation is backend's.
    assert any(span.name == "pattern.autonomous_agent" for span in spans)


def test_configure_tracing_without_exporter_is_noop_provider() -> None:
    provider = configure_tracing()
    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("probe"):
        pass
