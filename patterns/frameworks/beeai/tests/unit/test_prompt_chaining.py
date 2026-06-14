"""Prompt-chaining unit tests — BeeAI lane (Spec 006-2a Req 3.1/3.2/3.3, 9.2).

These tests exercise ``run_prompt_chain`` fully offline. A small recording
``ChatModel`` returns one scripted output per call *and* captures the user
prompt each step received, so the suite can assert two things the bare
``ScriptedChatModel`` (constant text, no recording) cannot:

* **Sequential chaining (Req 3.2)** — step *n*'s prompt must contain step
  *n-1*'s output, proving each output feeds the next step's input.
* **No silent continuation (Req 3.3)** — on a failed gate the model is called
  exactly as many times as there are pre-gate steps; the post-gate finalize
  call never happens, so early termination is observable, not inferred.

Observability for the BeeAI lane is the manual-span fallback (Req 9.1): the
span test wraps the run with :func:`patterns_beeai.observability.traced`,
mirroring ``test_observability.py`` for routing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from beeai_framework.backend.chat import ChatModel
from beeai_framework.backend.message import AssistantMessage, UserMessage
from beeai_framework.backend.types import ChatModelOutput, ChatModelStructureOutput
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from patterns_beeai.observability import configure_tracing, traced
from patterns_beeai.prompt_chaining import GATE_MIN_WORDS, run_prompt_chain
from tests.support.fake_chat_model import ScriptedChatModel

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from beeai_framework.backend.constants import ProviderName
    from beeai_framework.backend.types import ChatModelInput, ChatModelStructureInput
    from beeai_framework.context import RunContext


class _RecordingChatModel(ChatModel):
    """Replay ``outputs`` in call order, recording each call's user prompt.

    The distinct per-call outputs let a test prove chaining (a later step's
    captured prompt must contain the prior step's output); the recorded prompt
    list length proves early termination (finalize is never called on a failed
    gate). No network I/O happens at any point.
    """

    def __init__(self, outputs: list[str], prompts: list[str]) -> None:
        """Store the scripted outputs and a shared prompt-recording list."""
        super().__init__()
        self._outputs = outputs
        self._prompts = prompts
        self._cursor = 0

    @property
    def model_id(self) -> str:
        """Fake model identifier."""
        return "recording-fake"

    @property
    def provider_id(self) -> ProviderName:
        """Borrow the ``ollama`` vocabulary slot; no daemon is ever contacted."""
        return "ollama"

    async def _create(self, input: ChatModelInput, run: RunContext) -> ChatModelOutput:  # noqa: A002 - upstream signature
        del run
        user_texts = [
            message.text for message in input.messages if isinstance(message, UserMessage)
        ]
        self._prompts.append(user_texts[-1] if user_texts else "")
        index = self._cursor
        self._cursor = index + 1
        return ChatModelOutput(messages=[AssistantMessage(self._outputs[index])])

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
        msg = "_RecordingChatModel scripts only text"
        raise AssertionError(msg)


async def test_prompt_chain_runs_steps_in_order_and_finalizes_when_gate_passes() -> None:
    # Req 3.2: outline -> draft -> finalize, each consuming the prior output.
    prompts: list[str] = []
    llm = _RecordingChatModel(["one two three", "draft body has enough words", "FINAL"], prompts)

    result = await run_prompt_chain("write about widgets", llm=llm)

    assert [step.name for step in result.steps] == ["outline", "draft"]
    assert result.steps[0].output == "one two three"
    assert result.steps[1].output == "draft body has enough words"
    assert result.gate.passed is True
    assert result.final_output == "FINAL"
    # Chaining: each step's prompt carries the previous step's output forward.
    assert len(prompts) == 3
    assert "write about widgets" in prompts[0]
    assert "one two three" in prompts[1]
    assert "draft body has enough words" in prompts[2]


async def test_prompt_chain_stops_early_when_gate_fails() -> None:
    # Req 3.3: a thin draft fails the program-verification gate; the chain
    # terminates with final_output=None and never reaches the finalize call.
    prompts: list[str] = []
    llm = _RecordingChatModel(["outline text", "thin"], prompts)

    result = await run_prompt_chain("write about widgets", llm=llm)

    assert result.gate.passed is False
    assert result.final_output is None
    assert [step.name for step in result.steps] == ["outline", "draft"]
    assert result.steps[1].output == "thin"
    # No silent continuation: only the two pre-gate steps ran (finalize skipped).
    assert len(prompts) == 2


def test_gate_threshold_is_a_positive_word_count() -> None:
    # The gate is a real program-verification threshold, not a placeholder.
    assert GATE_MIN_WORDS >= 1


async def test_prompt_chain_emits_spans_into_injected_exporter() -> None:
    # Req 9.2: an instrumented run emits at least one span. The BeeAI lane uses
    # the manual-span fallback (Req 9.1), so the caller wraps the run in traced.
    exporter = InMemorySpanExporter()
    provider = configure_tracing(exporter)
    # ScriptedChatModel returns the same text for every step; "alpha beta gamma"
    # clears the gate (3 words) so the finalize step runs too.
    llm = ScriptedChatModel(text="alpha beta gamma")

    result = await traced(
        provider,
        "pattern.prompt_chaining",
        run_prompt_chain("hello", llm=llm),
    )

    assert result.final_output == "alpha beta gamma"
    spans = exporter.get_finished_spans()
    assert spans, "instrumented chain run must emit at least one span"
    # Req 9.3: assert only that the (manual pattern-level) span exists; token
    # aggregation is the backend's concern (double-counting trap).
    assert any(span.name == "pattern.prompt_chaining" for span in spans)
