"""Evaluator-optimizer unit tests — BeeAI lane (Spec 006-2a Req 5.1/5.2/5.3/5.4, 9.2).

These tests exercise ``run_evaluator_optimizer`` fully offline. Two seams are
used:

* the support ``VerdictSequencedChatModel`` (Task 4.2) replays an evaluator
  ``verdict`` vocabulary via ``create_structure`` (a cursor: ``revise → … →
  pass``) while answering generator text via ``create``, so both the ``passed``
  and ``max_iterations`` stop paths are reachable without a network (Req
  5.2/5.4). Dispatch is by *method* (generate vs. evaluate), so the bare fake
  cannot show feedback reflection.
* a small local recording ``ChatModel`` additionally captures each generator
  prompt, so the suite can prove the evaluator's ``revise`` feedback is
  reflected into the *next* generator input (Req 5.3) — mirroring the recording
  fake in ``test_prompt_chaining.py``.

Observability for the BeeAI lane is the manual-span fallback (Req 9.1): the span
test wraps the run with :func:`patterns_beeai.observability.traced`, mirroring
``test_parallelization.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from beeai_framework.backend.chat import ChatModel
from beeai_framework.backend.message import AssistantMessage, UserMessage
from beeai_framework.backend.types import ChatModelOutput, ChatModelStructureOutput
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from patterns_beeai.evaluator_optimizer import run_evaluator_optimizer
from patterns_beeai.observability import configure_tracing, traced
from tests.support.fake_chat_model import VerdictSequencedChatModel

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from beeai_framework.backend.constants import ProviderName
    from beeai_framework.backend.types import ChatModelInput, ChatModelStructureInput
    from beeai_framework.context import RunContext


class _RecordingChatModel(ChatModel):
    """Replay generator candidates + evaluator verdicts, recording gen prompts.

    Dispatches by method like the support fake: ``_create`` (the generator
    plain-text seam) replays the candidate cursor *and* records the user prompt
    it saw, so a test can assert feedback from iteration ``n-1`` reaches
    iteration ``n``; ``_create_structure`` (the evaluator seam) replays the
    verdict cursor. No network I/O happens at any point.
    """

    def __init__(
        self,
        candidates: list[str],
        verdicts: list[dict[str, str]],
        gen_prompts: list[str],
    ) -> None:
        """Store the scripted candidates/verdicts and a shared prompt list."""
        super().__init__()
        self._candidates = candidates
        self._verdicts = verdicts
        self._gen_prompts = gen_prompts
        self._gen_cursor = 0
        self._verdict_cursor = 0

    @property
    def model_id(self) -> str:
        """Fake model identifier."""
        return "recording-eval-fake"

    @property
    def provider_id(self) -> ProviderName:
        """Borrow the ``ollama`` vocabulary slot; no daemon is ever contacted."""
        return "ollama"

    async def _create(self, input: ChatModelInput, run: RunContext) -> ChatModelOutput:  # noqa: A002 - upstream signature
        del run
        user_texts = [
            message.text for message in input.messages if isinstance(message, UserMessage)
        ]
        self._gen_prompts.append(user_texts[-1] if user_texts else "")
        index = self._gen_cursor
        self._gen_cursor = index + 1
        return ChatModelOutput(messages=[AssistantMessage(self._candidates[index])])

    def _create_stream(
        self,
        input: ChatModelInput,  # noqa: A002 - upstream signature
        run: RunContext,
    ) -> AsyncGenerator[ChatModelOutput]:
        async def _gen() -> AsyncGenerator[ChatModelOutput]:
            yield await self._create(input, run)

        return _gen()

    async def _create_structure(
        self,
        input: ChatModelStructureInput[Any],  # noqa: A002 - upstream signature
        run: RunContext,
    ) -> ChatModelStructureOutput:
        del input, run
        index = self._verdict_cursor
        self._verdict_cursor = index + 1
        return ChatModelStructureOutput(object=self._verdicts[index])


async def test_loop_stops_on_pass_after_revise_transition() -> None:
    # Req 5.2/5.4: the loop iterates generate→evaluate, records every iteration,
    # and stops with stop_reason="passed" the moment a verdict is "pass" — even
    # though max_iterations allowed more.
    llm = VerdictSequencedChatModel(
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
    llm = VerdictSequencedChatModel(
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
    llm = _RecordingChatModel(
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
    llm = VerdictSequencedChatModel(
        verdicts=[{"verdict": "pass", "feedback": ""}],
        candidate="unused",
    )
    with pytest.raises(ValueError, match="max_iterations must be"):
        await run_evaluator_optimizer("task", llm=llm, max_iterations=0)


async def test_evaluator_optimizer_emits_spans_into_injected_exporter() -> None:
    # Req 9.2: an instrumented loop emits at least one span. The BeeAI lane uses
    # the manual-span fallback (Req 9.1), so the caller wraps the run in traced.
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
    # Req 9.3: assert only that the (manual pattern-level) span exists; token
    # aggregation is the backend's concern (double-counting trap).
    assert any(span.name == "pattern.evaluator_optimizer" for span in spans)
