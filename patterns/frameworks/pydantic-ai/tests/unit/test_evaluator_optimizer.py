"""Evaluator-optimizer unit tests (Spec 006-2a Req 5.1/5.2/5.3/5.4, 9.2).

These tests exercise ``run_evaluator_optimizer`` fully offline. Two seams are
used:

* the support ``verdict_sequenced_model`` (Task 4.1) replays an evaluator
  ``verdict`` vocabulary via a cursor (``revise → … → pass``) while answering
  generator text, so both the ``passed`` and ``max_iterations`` stop paths are
  reachable without a network (Req 5.2/5.4).
* a small local recording ``FunctionModel`` additionally captures each
  generator prompt, so the suite can prove the evaluator's ``revise`` feedback
  is reflected into the *next* generator input (Req 5.3) — something the bare
  cursor fake cannot show.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.instrumented import InstrumentationSettings

from patterns_pydantic_ai.evaluator_optimizer import run_evaluator_optimizer
from patterns_pydantic_ai.observability import configure_tracing
from tests.support.model_fakes import verdict_sequenced_model

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.models.function import AgentInfo


def _latest_user_prompt(messages: list[ModelMessage]) -> str:
    """Return the most recent user-prompt text in the message history."""
    for message in reversed(messages):
        for part in reversed(message.parts):
            if isinstance(part, UserPromptPart):
                content = part.content
                return content if isinstance(content, str) else str(content)
    return ""


def _recording_model(
    candidates: list[str],
    verdicts: list[dict[str, str]],
    gen_prompts: list[str],
) -> FunctionModel:
    """Replay generator candidates + evaluator verdicts, recording gen prompts.

    Dispatches on ``info.output_tools`` like the support fake: a structured
    (verdict) request replays the verdict cursor; a plain-text (generator)
    request replays the candidate cursor *and* records the prompt it saw, so a
    test can assert feedback from iteration ``n-1`` reaches iteration ``n``.
    """
    gen_cursor = [0]
    verdict_cursor = [0]

    def _respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if info.output_tools:
            tool = info.output_tools[0]
            index = verdict_cursor[0]
            verdict_cursor[0] = index + 1
            return ModelResponse(parts=[ToolCallPart(tool.name, verdicts[index])])
        gen_prompts.append(_latest_user_prompt(messages))
        index = gen_cursor[0]
        gen_cursor[0] = index + 1
        return ModelResponse(parts=[TextPart(candidates[index])])

    return FunctionModel(_respond, model_name="fake-eval-rec")


async def test_loop_stops_on_pass_after_revise_transition() -> None:
    # Req 5.2/5.4: the loop iterates generate→evaluate, records every
    # iteration, and stops with stop_reason="passed" the moment a verdict is
    # "pass" — even though max_iterations allowed more.
    model = verdict_sequenced_model(
        verdicts=[
            {"verdict": "revise", "feedback": "add detail"},
            {"verdict": "pass", "feedback": "looks good"},
        ],
        candidate=["draft one", "draft two final"],
    )

    result = await run_evaluator_optimizer("write a summary", model=model, max_iterations=3)

    assert result.stop_reason == "passed"
    assert result.final_output == "draft two final"
    assert [it.index for it in result.iterations] == [0, 1]
    assert [it.verdict for it in result.iterations] == ["revise", "pass"]
    assert result.iterations[0].candidate == "draft one"
    assert result.iterations[0].feedback == "add detail"


async def test_loop_stops_at_max_iterations_when_never_passing() -> None:
    # Req 5.4 / Req 7.3 contract-violation case: every verdict is "revise", so
    # the loop exhausts max_iterations and stops with that reason, carrying the
    # last candidate as the (best-effort) final_output.
    model = verdict_sequenced_model(
        verdicts=[
            {"verdict": "revise", "feedback": "f0"},
            {"verdict": "revise", "feedback": "f1"},
            {"verdict": "revise", "feedback": "f2"},
        ],
        candidate=["c0", "c1", "c2"],
    )

    result = await run_evaluator_optimizer("optimize this", model=model, max_iterations=3)

    assert result.stop_reason == "max_iterations"
    assert len(result.iterations) == 3
    assert all(it.verdict == "revise" for it in result.iterations)
    assert result.final_output == "c2"


async def test_revise_feedback_flows_into_next_generator_input() -> None:
    # Req 5.3: when the evaluator returns "revise", its feedback (and the prior
    # candidate) must appear in the next generator prompt, proving the loop
    # actually conditions the next attempt on the critique.
    gen_prompts: list[str] = []
    model = _recording_model(
        candidates=["first attempt", "second attempt"],
        verdicts=[
            {"verdict": "revise", "feedback": "NEEDS_CITATIONS"},
            {"verdict": "pass", "feedback": "ok"},
        ],
        gen_prompts=gen_prompts,
    )

    result = await run_evaluator_optimizer("explain caching", model=model, max_iterations=3)

    assert result.stop_reason == "passed"
    assert len(gen_prompts) == 2
    # First generator prompt seeds from the task only.
    assert "explain caching" in gen_prompts[0]
    # Second generator prompt reflects the evaluator feedback and prior draft.
    assert "NEEDS_CITATIONS" in gen_prompts[1]
    assert "first attempt" in gen_prompts[1]


async def test_rejects_non_positive_iteration_cap() -> None:
    # max_iterations < 1 would silently produce an empty optimization run with
    # no candidate ever generated; reject it loudly instead.
    model = verdict_sequenced_model(
        verdicts=[{"verdict": "pass", "feedback": ""}],
        candidate="unused",
    )
    with pytest.raises(ValueError, match="max_iterations must be"):
        await run_evaluator_optimizer("task", model=model, max_iterations=0)


async def test_evaluator_optimizer_emits_spans_into_injected_exporter() -> None:
    # Req 9.2: an instrumented loop emits at least one (leaf gen_ai) span.
    exporter = InMemorySpanExporter()
    provider = configure_tracing(exporter)
    settings = InstrumentationSettings(tracer_provider=provider)
    model = verdict_sequenced_model(
        verdicts=[{"verdict": "pass", "feedback": "good"}],
        candidate="answer",
    )

    result = await run_evaluator_optimizer(
        "hello", model=model, max_iterations=2, instrumentation=settings
    )

    assert result.stop_reason == "passed"
    spans = exporter.get_finished_spans()
    assert spans, "instrumented evaluator-optimizer run must emit at least one span"
    # Req 9.3: assert only that leaf LLM spans exist; token aggregation is the
    # backend's concern (double-counting trap).
    assert any("gen_ai" in str(span.attributes) for span in spans)
