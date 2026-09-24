"""Autonomous-agent unit tests (Spec 006-2a Req 6.1-6.6, 7.2/7.3, 9.1, 10.3).

These tests exercise ``run_autonomous_agent`` fully offline. The loop is a manual
tool loop on chat primitives, so the support ``turn_sequenced_model`` (Task 4.1)
replays a scripted ``tool call → environment feedback → final answer`` sequence,
advancing by the number of ``ToolReturnPart`` entries already in history (Req 7.2).
``StubTool`` is the deterministic in-memory tool. Each scripted turn carries a
fixed token count surfaced on ``ModelResponse.usage``, so the ``_budget_spent``
seam — and therefore the ``budget_exceeded`` guardrail — fires deterministically.

The four contract-level guardrails (Req 10.3 defense-in-depth) each get a
violation test: allowed-tools refusal (6.4), human-approval denial (6.5), budget
overrun (6.6), and the ``max_iterations`` cutoff (6.3), plus the happy path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.instrumented import InstrumentationSettings
from pydantic_ai.usage import RequestUsage

from patterns_pydantic_ai.autonomous_agent import run_autonomous_agent
from patterns_pydantic_ai.observability import configure_tracing
from tests.support.model_fakes import FinalTurn, StubTool, ToolTurn, turn_sequenced_model

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.models.function import AgentInfo


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


@dataclass
class _DescribedTool:
    """Tool carrying the optional ``description``/``parameters_json_schema``
    duck-typed extras ``_tool_definitions`` forwards when present."""

    name: str
    description: str
    schema: dict[str, object]
    dangerous: bool = False

    @property
    def parameters_json_schema(self) -> dict[str, object]:
        """Expose ``schema`` under the attribute name ``_tool_definitions`` reads."""
        return self.schema

    def run(self, args: str) -> str:
        """Unused by these tests; present only to satisfy the ``Tool`` Protocol."""
        return args


def _dict_then_none_args_model() -> FunctionModel:
    """Emit a dict-args tool call, then a None-args tool call, then a final answer.

    Advances by the number of ``ToolReturnPart`` entries in history (like the
    support fake), exercising the loop's ``_args_text`` normalization of the two
    non-string ``ToolCallPart.args`` shapes a real model can emit.
    """

    def _respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        index = sum(
            1 for message in messages for part in message.parts if isinstance(part, ToolReturnPart)
        )
        usage = RequestUsage(output_tokens=1)
        if index == 0:
            return ModelResponse(
                parts=[ToolCallPart("edit", {"path": "a", "mode": "w"})], usage=usage
            )
        if index == 1:
            return ModelResponse(parts=[ToolCallPart("edit", None)], usage=usage)
        return ModelResponse(parts=[TextPart("done")], usage=usage)

    return FunctionModel(_respond, model_name="fake-args")


async def test_completes_with_final_answer_after_tool_call() -> None:
    # Req 6.1/6.2: a tool call followed by a final answer completes the loop,
    # recording the executed step with the tool's observation and per-turn
    # budget, and stopping with stop_reason="completed".
    model = turn_sequenced_model(
        [
            ToolTurn(tool="lookup", args="q", tokens=3),
            FinalTurn(text="the answer is 42", tokens=2),
        ]
    )

    result = await run_autonomous_agent(
        "find the answer",
        model=model,
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


async def test_stops_with_disallowed_tool_outside_allowed_list() -> None:
    # Req 6.4 (least privilege): a call to a tool absent from allowed_tools is
    # refused — never executed — the refused attempt is recorded, and the loop
    # stops with stop_reason="disallowed_tool" (a hard stop, distinct from
    # denied). Only the disallowed turn is scripted: if the loop wrongly
    # continued it would request a second turn and the fake would fail loudly.
    model = turn_sequenced_model(
        [
            ToolTurn(tool="shell", args="rm -rf /", tokens=1),
        ]
    )

    result = await run_autonomous_agent(
        "do the task",
        model=model,
        max_iterations=5,
        allowed_tools=[StubTool(name="search", observation="results")],
        approval_hook=_approve_all,
        budget=100,
    )

    assert result.stop_reason == "disallowed_tool"
    assert result.final_output is None
    assert len(result.steps) == 1
    assert result.steps[0].tool == "shell"
    # The refused tool was not executed: the observation is the refusal marker,
    # never a tool-produced observation.
    assert "not in allowed_tools" in result.steps[0].observation


async def test_stops_with_denied_when_approval_hook_rejects_dangerous_tool() -> None:
    # Req 6.5: a dangerous tool whose approval_hook returns False is not
    # executed; the loop stops with stop_reason="denied" and no final_output.
    model = turn_sequenced_model([ToolTurn(tool="deploy", args="prod", tokens=2)])

    result = await run_autonomous_agent(
        "ship it",
        model=model,
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
    model = turn_sequenced_model(
        [
            ToolTurn(tool="probe", args="a", tokens=3),
            ToolTurn(tool="probe", args="b", tokens=3),
            FinalTurn(text="unreached", tokens=1),
        ]
    )

    result = await run_autonomous_agent(
        "keep probing",
        model=model,
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
    model = turn_sequenced_model(
        [
            ToolTurn(tool="probe", args="a", tokens=1),
            ToolTurn(tool="probe", args="b", tokens=1),
        ]
    )

    result = await run_autonomous_agent(
        "loop forever",
        model=model,
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
    model = turn_sequenced_model([FinalTurn(text="unused", tokens=0)])
    with pytest.raises(ValueError, match="max_iterations must be"):
        await run_autonomous_agent(
            "task",
            model=model,
            max_iterations=0,
            allowed_tools=[],
            approval_hook=_approve_all,
            budget=10,
        )


async def test_rejects_negative_budget() -> None:
    # A negative budget is nonsensical for an unbounded-consumption guardrail and
    # would make every run trip budget_exceeded; reject it loudly.
    model = turn_sequenced_model([FinalTurn(text="unused", tokens=0)])
    with pytest.raises(ValueError, match="budget must be"):
        await run_autonomous_agent(
            "task",
            model=model,
            max_iterations=3,
            allowed_tools=[],
            approval_hook=_approve_all,
            budget=-1,
        )


async def test_rejects_more_than_twenty_allowed_tools() -> None:
    # X-6b: too many tools on one agent degrades selection accuracy; reject
    # loudly rather than silently letting the agent choose among 21+ options.
    # The fix is subagents or Tool RAG, never raising this cap.
    model = turn_sequenced_model([FinalTurn(text="unused", tokens=0)])
    too_many = [StubTool(name=f"tool_{i}") for i in range(21)]
    with pytest.raises(ValueError, match="exceeding the 20-tool budget"):
        await run_autonomous_agent(
            "task",
            model=model,
            max_iterations=3,
            allowed_tools=too_many,
            approval_hook=_approve_all,
            budget=10,
        )


async def test_accepts_exactly_twenty_allowed_tools() -> None:
    # The boundary itself must not be rejected -- only exceeding it.
    model = turn_sequenced_model([FinalTurn(text="done", tokens=1)])
    exactly_twenty = [StubTool(name=f"tool_{i}") for i in range(20)]
    result = await run_autonomous_agent(
        "task",
        model=model,
        max_iterations=3,
        allowed_tools=exactly_twenty,
        approval_hook=_approve_all,
        budget=10,
    )
    assert result.stop_reason == "completed"


async def test_normalizes_dict_and_none_tool_call_args_for_tool_run() -> None:
    # A real model can emit ToolCallPart.args as a dict or None, not just a
    # string; the loop normalizes both before forwarding to Tool.run (dict ->
    # sorted JSON, None -> empty string) so tools receive a stable string.
    tool = _RecordingTool(name="edit")

    result = await run_autonomous_agent(
        "edit files",
        model=_dict_then_none_args_model(),
        max_iterations=5,
        allowed_tools=[tool],
        approval_hook=_approve_all,
        budget=100,
    )

    assert result.stop_reason == "completed"
    assert tool.received == ['{"mode": "w", "path": "a"}', ""]
    assert [step.observation for step in result.steps] == ["recorded", "recorded"]


async def test_autonomous_agent_emits_spans_into_injected_exporter() -> None:
    # Req 9.1: an instrumented run emits at least one (leaf gen_ai) span.
    exporter = InMemorySpanExporter()
    provider = configure_tracing(exporter)
    settings = InstrumentationSettings(tracer_provider=provider)
    model = turn_sequenced_model([FinalTurn(text="done", tokens=1)])

    result = await run_autonomous_agent(
        "hello",
        model=model,
        max_iterations=2,
        allowed_tools=[],
        approval_hook=_approve_all,
        budget=10,
        instrumentation=settings,
    )

    assert result.stop_reason == "completed"
    spans = exporter.get_finished_spans()
    assert spans, "instrumented autonomous-agent run must emit at least one span"
    # Req 9.3: assert only that leaf LLM spans exist; token aggregation is the
    # backend's concern (double-counting trap).
    assert any("gen_ai" in str(span.attributes) for span in spans)


class TestToolSchemaSentToModel:
    """Before this, ``run_autonomous_agent`` sent an empty tool schema on
    every request -- no ``function_tools`` at all -- so a real model had no
    way to learn a tool existed. These tests capture the actual
    ``ModelRequestParameters`` a request receives (via a scripted
    ``FunctionModel``) and assert the ``allowed_tools`` entries reach it."""

    async def test_allowed_tools_reach_the_model_as_function_tools(self) -> None:
        captured: list[AgentInfo] = []

        def fn(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            captured.append(info)
            return ModelResponse(parts=[TextPart("done")], usage=RequestUsage(output_tokens=1))

        result = await run_autonomous_agent(
            "task",
            model=FunctionModel(fn),
            max_iterations=1,
            allowed_tools=[StubTool(name="search"), StubTool(name="lookup")],
            approval_hook=_approve_all,
            budget=10,
        )

        assert result.stop_reason == "completed"
        assert len(captured) == 1
        sent_names = {tool.name for tool in captured[0].function_tools}
        assert sent_names == {"search", "lookup"}

    async def test_a_tool_without_its_own_schema_gets_the_generic_fallback(self) -> None:
        captured: list[AgentInfo] = []

        def fn(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            captured.append(info)
            return ModelResponse(parts=[TextPart("done")], usage=RequestUsage(output_tokens=1))

        await run_autonomous_agent(
            "task",
            model=FunctionModel(fn),
            max_iterations=1,
            allowed_tools=[StubTool(name="search")],
            approval_hook=_approve_all,
            budget=10,
        )

        (sent,) = captured[0].function_tools
        assert sent.name == "search"
        assert sent.description is not None
        assert "search" in sent.description
        assert sent.parameters_json_schema["required"] == ["args"]

    async def test_a_tool_with_its_own_description_and_schema_is_forwarded(self) -> None:
        captured: list[AgentInfo] = []

        def fn(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            captured.append(info)
            return ModelResponse(parts=[TextPart("done")], usage=RequestUsage(output_tokens=1))

        schema: dict[str, object] = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }
        tool = _DescribedTool(name="web_search", description="Search the web.", schema=schema)

        await run_autonomous_agent(
            "task",
            model=FunctionModel(fn),
            max_iterations=1,
            allowed_tools=[tool],
            approval_hook=_approve_all,
            budget=10,
        )

        (sent,) = captured[0].function_tools
        assert sent.description == "Search the web."
        assert sent.parameters_json_schema == schema


class TestMultipleToolCallsInOneTurn:
    """A real model can return more than one ``ToolCallPart`` in a single
    turn; every one of them must be executed, recorded, and answered (a
    provider rejects a follow-up request carrying an assistant turn with an
    unanswered tool call)."""

    async def test_both_calls_execute_and_the_loop_continues(self) -> None:
        def fn(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
            returns = sum(
                1
                for message in messages
                for part in message.parts
                if isinstance(part, ToolReturnPart)
            )
            if returns == 0:
                return ModelResponse(
                    parts=[ToolCallPart("a", "x"), ToolCallPart("b", "y")],
                    usage=RequestUsage(output_tokens=5),
                )
            return ModelResponse(parts=[TextPart("done")], usage=RequestUsage(output_tokens=1))

        result = await run_autonomous_agent(
            "task",
            model=FunctionModel(fn),
            max_iterations=3,
            allowed_tools=[
                StubTool(name="a", observation="A"),
                StubTool(name="b", observation="B"),
            ],
            approval_hook=_approve_all,
            budget=100,
        )

        assert result.stop_reason == "completed"
        assert [step.tool for step in result.steps] == ["a", "b"]
        assert [step.observation for step in result.steps] == ["A", "B"]
        # The turn's tokens are attributed once (to the first call), not
        # once per call in the turn.
        assert [step.budget_spent for step in result.steps] == [5, 0]
        assert result.total_budget_spent == 5

    async def test_a_disallowed_second_call_stops_without_a_dangling_return(self) -> None:
        def fn(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
            return ModelResponse(
                parts=[ToolCallPart("a", "x"), ToolCallPart("shell", "rm -rf /")],
                usage=RequestUsage(output_tokens=4),
            )

        result = await run_autonomous_agent(
            "task",
            model=FunctionModel(fn),
            max_iterations=3,
            allowed_tools=[StubTool(name="a", observation="A")],
            approval_hook=_approve_all,
            budget=100,
        )

        assert result.stop_reason == "disallowed_tool"
        assert [step.tool for step in result.steps] == ["a", "shell"]
        assert result.steps[0].observation == "A"
        assert "not in allowed_tools" in result.steps[1].observation
        assert result.total_budget_spent == 4
