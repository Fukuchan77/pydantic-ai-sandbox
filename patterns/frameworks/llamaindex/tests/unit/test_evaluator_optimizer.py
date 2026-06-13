"""Evaluator-optimizer unit tests — LlamaIndex lane (Spec 006-2a Req 5.1/5.2/5.3/5.4, 9.2).

These tests exercise ``run_evaluator_optimizer`` fully offline. Two seams are
used:

* the support ``VerdictSequencedLLM`` (Task 4.3) replays an evaluator ``verdict``
  vocabulary (a cursor: ``revise → … → pass``) when the quoted ``"verdict"``
  token appears in a structured-predict prompt, while answering generator text
  for plain completions, so both the ``passed`` and ``max_iterations`` stop paths
  are reachable without a network (Req 5.2/5.4). Dispatch is by *prompt content*
  (the structured schema embeds ``"verdict"``), so the bare fake cannot show
  feedback reflection.
* a small local recording ``CustomLLM`` additionally captures each generator
  prompt, so the suite can prove the evaluator's ``revise`` feedback is reflected
  into the *next* generator input (Req 5.3) — mirroring the recording fake in
  ``test_prompt_chaining.py``.

Observability for the LlamaIndex lane is OpenInference's process-global
``LlamaIndexInstrumentor`` (Req 9.1): the span test installs it, runs the loop,
then detaches it, mirroring ``test_parallelization.py``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from llama_index.core.llms import (
    CompletionResponse,
    CompletionResponseGen,
    CustomLLM,
    LLMMetadata,
)

# Untyped upstream decorator factory; ignore is scoped to the imported name.
from llama_index.core.llms.callbacks import (
    llm_completion_callback,  # pyright: ignore[reportUnknownVariableType]
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import PrivateAttr

from patterns_llamaindex.evaluator_optimizer import run_evaluator_optimizer
from patterns_llamaindex.observability import (
    configure_tracing,
    instrument_llamaindex,
    uninstrument_llamaindex,
)
from tests.support.fake_llm import VerdictSequencedLLM


class _RecordingLLM(CustomLLM):
    """Replay generator candidates + evaluator verdicts, recording gen prompts.

    Dispatches by prompt content like the support fake: a structured-predict
    prompt embeds the ``_Evaluation`` schema, so the quoted ``"verdict"`` token
    selects the verdict cursor; every other completion is a generator call, whose
    prompt is recorded so a test can assert feedback from iteration ``n-1`` reaches
    iteration ``n``. ``CustomLLM`` derives ``acomplete`` / ``astructured_predict``
    from this sync ``complete`` seam, so no network I/O happens at any point.
    """

    _candidates: list[str] = PrivateAttr(default_factory=list[str])
    _verdicts: list[dict[str, object]] = PrivateAttr(default_factory=list[dict[str, object]])
    _gen_prompts: list[str] = PrivateAttr(default_factory=list[str])
    _gen_cursor: int = PrivateAttr(default=0)
    _verdict_cursor: int = PrivateAttr(default=0)

    def __init__(
        self,
        candidates: list[str],
        verdicts: list[dict[str, object]],
        gen_prompts: list[str],
    ) -> None:
        """Store scripted candidates/verdicts and a shared prompt-recording list."""
        super().__init__()
        self._candidates = candidates
        self._verdicts = verdicts
        self._gen_prompts = gen_prompts

    @property
    def metadata(self) -> LLMMetadata:
        """Advertise a plain (non-function-calling) completion model."""
        return LLMMetadata(model_name="recording-eval-fake", is_function_calling_model=False)

    @llm_completion_callback()  # pyright: ignore[reportUntypedFunctionDecorator]
    def complete(self, prompt: str, formatted: bool = False, **kwargs: Any) -> CompletionResponse:
        """Dispatch an evaluator verdict (structured prompt) or a recorded candidate."""
        del formatted, kwargs
        if '"verdict"' in prompt:
            index = self._verdict_cursor
            self._verdict_cursor = index + 1
            return CompletionResponse(text=json.dumps(self._verdicts[index]))
        self._gen_prompts.append(prompt)
        index = self._gen_cursor
        self._gen_cursor = index + 1
        return CompletionResponse(text=self._candidates[index])

    @llm_completion_callback()  # pyright: ignore[reportUntypedFunctionDecorator]
    def stream_complete(
        self, prompt: str, formatted: bool = False, **kwargs: Any
    ) -> CompletionResponseGen:
        """Stream the single canned completion as one chunk."""
        del formatted, kwargs

        def _gen() -> CompletionResponseGen:
            yield self.complete(prompt)

        return _gen()


async def test_loop_stops_on_pass_after_revise_transition() -> None:
    # Req 5.2/5.4: the loop iterates generate→evaluate, records every iteration,
    # and stops with stop_reason="passed" the moment a verdict is "pass" — even
    # though max_iterations allowed more.
    llm = VerdictSequencedLLM(
        verdicts=[
            {"verdict": "revise", "feedback": "add detail"},
            {"verdict": "pass", "feedback": "looks good"},
        ],
        candidate=["draft one", "draft two final"],
    )

    result = await run_evaluator_optimizer("write a summary", llm=llm, max_iterations=3)

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
    llm = VerdictSequencedLLM(
        verdicts=[
            {"verdict": "revise", "feedback": "f0"},
            {"verdict": "revise", "feedback": "f1"},
            {"verdict": "revise", "feedback": "f2"},
        ],
        candidate=["c0", "c1", "c2"],
    )

    result = await run_evaluator_optimizer("optimize this", llm=llm, max_iterations=3)

    assert result.stop_reason == "max_iterations"
    assert len(result.iterations) == 3
    assert all(it.verdict == "revise" for it in result.iterations)
    assert result.final_output == "c2"


async def test_revise_feedback_flows_into_next_generator_input() -> None:
    # Req 5.3: when the evaluator returns "revise", its feedback (and the prior
    # candidate) must appear in the next generator prompt, proving the loop
    # actually conditions the next attempt on the critique.
    gen_prompts: list[str] = []
    llm = _RecordingLLM(
        candidates=["first attempt", "second attempt"],
        verdicts=[
            {"verdict": "revise", "feedback": "NEEDS_CITATIONS"},
            {"verdict": "pass", "feedback": "ok"},
        ],
        gen_prompts=gen_prompts,
    )

    result = await run_evaluator_optimizer("explain caching", llm=llm, max_iterations=3)

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
    llm = VerdictSequencedLLM(
        verdicts=[{"verdict": "pass", "feedback": ""}],
        candidate="unused",
    )
    with pytest.raises(ValueError, match="max_iterations must be"):
        await run_evaluator_optimizer("task", llm=llm, max_iterations=0)


async def test_evaluator_optimizer_emits_spans_into_injected_exporter() -> None:
    # Req 9.2: an instrumented loop emits at least one span. The LlamaIndex lane
    # uses OpenInference's process-global instrumentor (Req 9.1).
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
    # Req 9.3: existence of leaf LLM spans only — token aggregation is the
    # backend's concern (double-counting trap).
    assert any("llm" in span.name.lower() or "complete" in span.name.lower() for span in spans)
