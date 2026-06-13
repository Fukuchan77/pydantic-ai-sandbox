"""Prompt-chaining unit tests (Spec 006-2a Req 3.1/3.2/3.3, 9.2).

These tests exercise ``run_prompt_chain`` fully offline. A small recording
``FunctionModel`` returns one scripted output per call *and* captures the user
prompt each step received, so the suite can assert two things the bare
``scripted_model`` cannot:

* **Sequential chaining (Req 3.2)** — step *n*'s prompt must contain step
  *n-1*'s output, proving each output feeds the next step's input.
* **No silent continuation (Req 3.3)** — on a failed gate the model is called
  exactly as many times as there are pre-gate steps; the post-gate finalize
  call never happens, so early termination is observable, not inferred.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic_ai.messages import ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.instrumented import InstrumentationSettings

from patterns_pydantic_ai.observability import configure_tracing
from patterns_pydantic_ai.prompt_chaining import GATE_MIN_WORDS, run_prompt_chain
from tests.support.model_fakes import scripted_model

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


def _recording_model(outputs: list[str], prompts: list[str]) -> FunctionModel:
    """Replay ``outputs`` in call order, recording each call's user prompt.

    The distinct per-call outputs let a test prove chaining: a later step's
    captured prompt must contain the prior step's output.
    """
    cursor = [0]

    def _respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        prompts.append(_latest_user_prompt(messages))
        index = cursor[0]
        cursor[0] = index + 1
        return ModelResponse(parts=[TextPart(outputs[index])])

    return FunctionModel(_respond, model_name="fake-chain")


async def test_prompt_chain_runs_steps_in_order_and_finalizes_when_gate_passes() -> None:
    # Req 3.2: outline -> draft -> finalize, each consuming the prior output.
    prompts: list[str] = []
    model = _recording_model(["one two three", "draft body has enough words", "FINAL"], prompts)

    result = await run_prompt_chain("write about widgets", model=model)

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
    model = _recording_model(["outline text", "thin"], prompts)

    result = await run_prompt_chain("write about widgets", model=model)

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
    # Req 9.2: an instrumented run emits at least one (leaf gen_ai) span.
    exporter = InMemorySpanExporter()
    provider = configure_tracing(exporter)
    settings = InstrumentationSettings(tracer_provider=provider)
    # scripted_model returns the same plain text for every str step; "alpha
    # beta gamma" clears the gate so the finalize step runs too.
    model = scripted_model(text="alpha beta gamma")

    result = await run_prompt_chain("hello", model=model, instrumentation=settings)

    assert result.final_output == "alpha beta gamma"
    spans = exporter.get_finished_spans()
    assert spans, "instrumented chain run must emit at least one span"
    # Req 9.3: assert only that leaf LLM spans exist; aggregation is the
    # backend's concern (token double-counting trap).
    assert any("gen_ai" in str(span.attributes) for span in spans)
