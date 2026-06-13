"""Autonomous-agent unit tests — LlamaIndex lane (Spec 006-2a Req 6.1-6.6, 7.2/7.3, 9.1/9.2, 10.3).

These tests exercise ``run_autonomous_agent`` fully offline. The loop is a manual
tool loop on the LlamaIndex completion primitive (``llm.acomplete``), so the
support ``TurnSequencedLLM`` (Task 4.3) replays a scripted ``tool call → final
answer`` sequence via an internal call cursor — LlamaIndex exposes no tool-return
history at the model boundary, so the fake advances per ``complete`` rather than
by counting history entries (the pydantic-ai lane difference, plan line 165).
``CustomLLM`` is completion-only with no native tool-call parts, so a
:class:`ToolTurn` surfaces as a ``{"tool": ..., "args": ...}`` JSON action in the
completion text and a :class:`FinalTurn` as plain text; the loop treats a
completion that parses to an object carrying a ``"tool"`` key as a tool call and
anything else as the final answer. ``StubTool`` is the deterministic in-memory
tool. Each scripted turn carries a fixed token count surfaced on
``CompletionResponse.raw``, so the ``_budget_spent`` seam — and therefore the
``budget_exceeded`` guardrail — fires deterministically.

The four contract-level guardrails (Req 10.3 defense-in-depth) each get a
violation test: allowed-tools refusal (6.4), human-approval denial (6.5), budget
overrun (6.6), and the ``max_iterations`` cutoff (6.3), plus the happy path.

Observability for the LlamaIndex lane is OpenInference's process-global
``LlamaIndexInstrumentor`` (Req 9.1): the span test installs it, runs the loop,
then detaches it, mirroring ``test_evaluator_optimizer.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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

from patterns_llamaindex.autonomous_agent import run_autonomous_agent
from patterns_llamaindex.observability import (
    configure_tracing,
    instrument_llamaindex,
    uninstrument_llamaindex,
)
from tests.support.fake_llm import (
    FinalTurn,
    StubTool,
    ToolTurn,
    TurnSequencedLLM,
)


def _approve_all(_tool: str, _args: str) -> bool:
    """Approval hook that approves every dangerous tool call."""
    return True


def _deny_all(_tool: str, _args: str) -> bool:
    """Approval hook that denies every dangerous tool call."""
    return False


@dataclass
class _RecordingTool:
    """Tool (contracts ``Tool`` Protocol) that records the args string it ran with."""

    name: str
    received: list[str] = field(default_factory=list[str])
    dangerous: bool = False

    def run(self, args: str) -> str:
        """Record ``args`` and return a fixed observation."""
        self.received.append(args)
        return "recorded"


@dataclass(frozen=True)
class _RawTurn:
    """A scripted completion with an explicit ``raw`` provider payload."""

    text: str
    raw: object


class _RawScriptedLLM(CustomLLM):
    """Completion fake scripting ``(text, raw)`` pairs to drive the budget seam.

    The support ``TurnSequencedLLM`` always surfaces a well-formed
    ``raw["usage"]["total_tokens"]`` record, so this local fake exists to drive
    ``_budget_spent`` past its defensive branches — a provider response whose
    ``raw`` is absent (``None``) or carries no ``usage`` key contributes zero —
    and to feed a JSON-object-without-``tool`` completion, which the loop treats
    as a final answer (mirrors the local recording fakes in
    ``test_prompt_chaining.py`` / ``test_evaluator_optimizer.py``).
    """

    _turns: list[_RawTurn] = PrivateAttr(default_factory=list[_RawTurn])
    _cursor: int = PrivateAttr(default=0)

    def __init__(self, turns: list[_RawTurn]) -> None:
        """Store the scripted turns; the call cursor starts at zero."""
        super().__init__()
        self._turns = turns

    @property
    def metadata(self) -> LLMMetadata:
        """Advertise a plain (non-function-calling) completion model."""
        return LLMMetadata(model_name="raw-scripted-fake", is_function_calling_model=False)

    @llm_completion_callback()  # pyright: ignore[reportUntypedFunctionDecorator]
    def complete(self, prompt: str, formatted: bool = False, **kwargs: Any) -> CompletionResponse:
        """Return the next scripted (text, raw) completion, advancing the cursor."""
        del prompt, formatted, kwargs
        turn = self._turns[self._cursor]
        self._cursor += 1
        return CompletionResponse(text=turn.text, raw=turn.raw)

    @llm_completion_callback()  # pyright: ignore[reportUntypedFunctionDecorator]
    def stream_complete(
        self, prompt: str, formatted: bool = False, **kwargs: Any
    ) -> CompletionResponseGen:
        """Stream the single canned completion as one chunk."""
        del formatted, kwargs

        def _gen() -> CompletionResponseGen:
            yield self.complete(prompt)

        return _gen()


async def test_completes_with_final_answer_after_tool_call() -> None:
    # Req 6.1/6.2: a tool call followed by a final answer completes the loop,
    # recording the executed step with the tool's observation and per-turn
    # budget, and stopping with stop_reason="completed".
    llm = TurnSequencedLLM(
        [
            ToolTurn(tool="lookup", args="q", tokens=3),
            FinalTurn(text="the answer is 42", tokens=2),
        ]
    )

    result = await run_autonomous_agent(
        "find the answer",
        llm=llm,
        max_iterations=5,
        allowed_tools=[StubTool(name="lookup", observation="42")],
        approval_hook=_approve_all,
        budget=100,
    )

    assert result.stop_reason == "completed"
    assert result.final_output == "the answer is 42"
    assert len(result.steps) == 1
    assert result.steps[0].index == 0
    assert result.steps[0].tool == "lookup"
    assert result.steps[0].observation == "42"
    assert result.steps[0].budget_spent == 3
    # Only the recorded tool steps count toward the budget tally (Req 6.6).
    assert result.total_budget_spent == 3


async def test_forwards_tool_call_args_to_the_tool() -> None:
    # Req 6.1: the loop forwards the model's tool-call args verbatim to Tool.run
    # (the JSON action carries args as a plain string, so no normalization is
    # needed) and records the tool-produced observation.
    tool = _RecordingTool(name="edit")
    llm = TurnSequencedLLM(
        [
            ToolTurn(tool="edit", args="path=a", tokens=1),
            FinalTurn(text="done", tokens=1),
        ]
    )

    result = await run_autonomous_agent(
        "edit files",
        llm=llm,
        max_iterations=5,
        allowed_tools=[tool],
        approval_hook=_approve_all,
        budget=100,
    )

    assert result.stop_reason == "completed"
    assert tool.received == ["path=a"]
    assert result.steps[0].observation == "recorded"


async def test_refuses_tool_outside_allowed_list_and_continues() -> None:
    # Req 6.4 (least privilege): a call to a tool absent from allowed_tools is
    # refused — never executed — and a refusal observation is fed back so the
    # loop can continue to a legitimate completion.
    llm = TurnSequencedLLM(
        [
            ToolTurn(tool="shell", args="rm -rf /", tokens=1),
            FinalTurn(text="finished safely", tokens=1),
        ]
    )

    result = await run_autonomous_agent(
        "do the task",
        llm=llm,
        max_iterations=5,
        allowed_tools=[StubTool(name="search", observation="results")],
        approval_hook=_approve_all,
        budget=100,
    )

    assert result.stop_reason == "completed"
    assert result.final_output == "finished safely"
    assert len(result.steps) == 1
    assert result.steps[0].tool == "shell"
    # The refused tool was not executed: the observation is the refusal marker,
    # never a tool-produced observation.
    assert "not in allowed_tools" in result.steps[0].observation


async def test_stops_with_denied_when_approval_hook_rejects_dangerous_tool() -> None:
    # Req 6.5: a dangerous tool whose approval_hook returns False is not
    # executed; the loop stops with stop_reason="denied" and no final_output.
    llm = TurnSequencedLLM([ToolTurn(tool="deploy", args="prod", tokens=2)])

    result = await run_autonomous_agent(
        "ship it",
        llm=llm,
        max_iterations=5,
        allowed_tools=[StubTool(name="deploy", observation="deployed", dangerous=True)],
        approval_hook=_deny_all,
        budget=100,
    )

    assert result.stop_reason == "denied"
    assert result.final_output is None
    assert len(result.steps) == 1
    assert result.steps[0].tool == "deploy"
    # Not executed: the canned "deployed" observation must never appear.
    assert result.steps[0].observation != "deployed"
    assert result.total_budget_spent == 2


async def test_stops_with_budget_exceeded_when_cumulative_tokens_pass_budget() -> None:
    # Req 6.6 (unbounded-consumption guard): each turn spends 3 tokens; with a
    # budget of 5 the cumulative spend crosses the cap on the second step, which
    # stops the loop with stop_reason="budget_exceeded".
    llm = TurnSequencedLLM(
        [
            ToolTurn(tool="probe", args="a", tokens=3),
            ToolTurn(tool="probe", args="b", tokens=3),
            FinalTurn(text="unreached", tokens=1),
        ]
    )

    result = await run_autonomous_agent(
        "keep probing",
        llm=llm,
        max_iterations=10,
        allowed_tools=[StubTool(name="probe", observation="ok")],
        approval_hook=_approve_all,
        budget=5,
    )

    assert result.stop_reason == "budget_exceeded"
    assert result.final_output is None
    assert len(result.steps) == 2
    assert result.total_budget_spent == 6


async def test_stops_at_max_iterations_when_loop_never_finalizes() -> None:
    # Req 6.3: a loop that keeps requesting tools without ever producing a final
    # answer stops at max_iterations with no final_output.
    llm = TurnSequencedLLM(
        [
            ToolTurn(tool="probe", args="a", tokens=1),
            ToolTurn(tool="probe", args="b", tokens=1),
        ]
    )

    result = await run_autonomous_agent(
        "loop forever",
        llm=llm,
        max_iterations=2,
        allowed_tools=[StubTool(name="probe", observation="ok")],
        approval_hook=_approve_all,
        budget=100,
    )

    assert result.stop_reason == "max_iterations"
    assert result.final_output is None
    assert len(result.steps) == 2
    assert result.total_budget_spent == 2


async def test_rejects_non_positive_iteration_cap() -> None:
    # max_iterations < 1 would run zero iterations and silently produce an empty
    # agent run; reject it loudly instead.
    llm = TurnSequencedLLM([FinalTurn(text="unused", tokens=0)])
    with pytest.raises(ValueError, match="max_iterations must be"):
        await run_autonomous_agent(
            "task",
            llm=llm,
            max_iterations=0,
            allowed_tools=[],
            approval_hook=_approve_all,
            budget=10,
        )


async def test_rejects_negative_budget() -> None:
    # A negative budget is nonsensical for an unbounded-consumption guardrail and
    # would make every run trip budget_exceeded; reject it loudly.
    llm = TurnSequencedLLM([FinalTurn(text="unused", tokens=0)])
    with pytest.raises(ValueError, match="budget must be"):
        await run_autonomous_agent(
            "task",
            llm=llm,
            max_iterations=3,
            allowed_tools=[],
            approval_hook=_approve_all,
            budget=-1,
        )


async def test_autonomous_agent_emits_spans_into_injected_exporter() -> None:
    # Req 9.1/9.2: an instrumented run emits at least one span. The LlamaIndex
    # lane uses OpenInference's process-global instrumentor, so the test installs
    # it, runs the loop, then detaches it (mirroring test_evaluator_optimizer.py).
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
    # Req 9.3: existence of leaf LLM spans only — token aggregation is the
    # backend's concern (double-counting trap).
    assert any("llm" in span.name.lower() or "complete" in span.name.lower() for span in spans)


async def test_budget_seam_tolerates_responses_without_a_usage_record() -> None:
    # Req 6.6 robustness: the completion-only budget seam reads an opaque provider
    # payload, so a response whose raw carries no "usage" key (first turn) or omits
    # raw entirely (second turn) must contribute zero rather than raise. The second
    # turn also parses to a JSON object *without* a "tool" key, which the loop must
    # treat as the final answer — not a malformed tool call.
    llm = _RawScriptedLLM(
        [
            _RawTurn(text='{"tool": "noop", "args": ""}', raw={"other": 1}),
            _RawTurn(text='{"answer": "all done"}', raw=None),
        ]
    )

    result = await run_autonomous_agent(
        "do it",
        llm=llm,
        max_iterations=5,
        allowed_tools=[StubTool(name="noop", observation="ok")],
        approval_hook=_approve_all,
        budget=100,
    )

    assert result.stop_reason == "completed"
    assert result.final_output == '{"answer": "all done"}'
    # Neither turn surfaced a usable usage record, so nothing was charged.
    assert result.total_budget_spent == 0
    assert len(result.steps) == 1
    assert result.steps[0].tool == "noop"
    assert result.steps[0].budget_spent == 0
