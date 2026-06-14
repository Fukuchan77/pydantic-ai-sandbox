"""Prompt-chaining unit tests — LlamaIndex lane (Spec 006-2a Req 3.1/3.2/3.3, 9.2).

These tests exercise ``run_prompt_chain`` fully offline. A small recording
``CustomLLM`` returns one scripted completion per call *and* captures the prompt
each step received, so the suite can assert two things the bare ``ScriptedLLM``
(constant text, no recording) cannot:

* **Sequential chaining (Req 3.2)** — step *n*'s prompt must contain step
  *n-1*'s output, proving each output feeds the next step's input.
* **No silent continuation (Req 3.3)** — on a failed gate the model is called
  exactly as many times as there are pre-gate steps; the post-gate finalize
  call never happens, so early termination is observable, not inferred.

Observability for the LlamaIndex lane is OpenInference's process-global
``LlamaIndexInstrumentor`` (Req 9.1): the span test installs it, runs the chain,
then detaches it, mirroring ``test_observability.py`` for routing.
"""

from __future__ import annotations

from typing import Any

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

from patterns_llamaindex.observability import (
    configure_tracing,
    instrument_llamaindex,
    uninstrument_llamaindex,
)
from patterns_llamaindex.prompt_chaining import GATE_MIN_WORDS, run_prompt_chain
from tests.support.fake_llm import ScriptedLLM


class _RecordingLLM(CustomLLM):
    """Replay ``outputs`` in call order, recording each call's prompt.

    The distinct per-call outputs let a test prove chaining (a later step's
    captured prompt must contain the prior step's output); the recorded prompt
    list length proves early termination (finalize is never called on a failed
    gate). ``CustomLLM`` derives ``acomplete`` from the sync ``complete`` seam,
    so a single completion path drives every workflow step with no network I/O.
    """

    _outputs: list[str] = PrivateAttr(default_factory=list[str])
    _prompts: list[str] = PrivateAttr(default_factory=list[str])
    _cursor: int = PrivateAttr(default=0)

    def __init__(self, outputs: list[str], prompts: list[str]) -> None:
        """Store scripted outputs and a shared prompt-recording list."""
        super().__init__()
        self._outputs = outputs
        self._prompts = prompts

    @property
    def metadata(self) -> LLMMetadata:
        """Advertise a plain (non-function-calling) completion model."""
        return LLMMetadata(model_name="recording-fake", is_function_calling_model=False)

    @llm_completion_callback()  # pyright: ignore[reportUntypedFunctionDecorator]
    def complete(self, prompt: str, formatted: bool = False, **kwargs: Any) -> CompletionResponse:
        """Record the prompt and return the next scripted completion."""
        del formatted, kwargs
        self._prompts.append(prompt)
        index = self._cursor
        self._cursor = index + 1
        return CompletionResponse(text=self._outputs[index])

    @llm_completion_callback()  # pyright: ignore[reportUntypedFunctionDecorator]
    def stream_complete(
        self, prompt: str, formatted: bool = False, **kwargs: Any
    ) -> CompletionResponseGen:
        """Stream the single canned completion as one chunk."""
        del formatted, kwargs

        def _gen() -> CompletionResponseGen:
            yield self.complete(prompt)

        return _gen()


async def test_prompt_chain_runs_steps_in_order_and_finalizes_when_gate_passes() -> None:
    # Req 3.2: outline -> draft -> finalize, each consuming the prior output.
    prompts: list[str] = []
    llm = _RecordingLLM(["one two three", "draft body has enough words", "FINAL"], prompts)

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
    llm = _RecordingLLM(["outline text", "thin"], prompts)

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
    # Req 9.2: an instrumented run emits at least one span. The LlamaIndex lane
    # uses OpenInference's process-global instrumentor (Req 9.1).
    exporter = InMemorySpanExporter()
    provider = configure_tracing(exporter)
    instrumentor = instrument_llamaindex(provider)
    try:
        # ScriptedLLM returns the same text for every step; "alpha beta gamma"
        # clears the gate (3 words) so the finalize step runs too.
        llm = ScriptedLLM(text="alpha beta gamma")
        result = await run_prompt_chain("hello", llm=llm)
    finally:
        # Instrumentation is process-global; detach so other tests run clean.
        uninstrument_llamaindex(instrumentor)

    assert result.final_output == "alpha beta gamma"
    spans = exporter.get_finished_spans()
    assert spans, "instrumented chain run must emit at least one span"
    # Req 9.3: existence of leaf LLM spans only — token aggregation is the
    # backend's concern (double-counting trap).
    assert any("llm" in span.name.lower() or "complete" in span.name.lower() for span in spans)
