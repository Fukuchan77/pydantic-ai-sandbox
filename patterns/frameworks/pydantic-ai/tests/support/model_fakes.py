"""Scripted ``FunctionModel`` fakes for deterministic pattern tests.

``TestModel`` (used by the smoke test) generates schema-valid but
arbitrary data; the pattern tests instead need *chosen* routes, plans,
tool loops, votes, and verdicts.

This module mirrors the root repo's ``tests/support/model_fakes.py``
philosophy (fakes are tiny, explicit, and network-free) and carries two
generations of fakes:

* ``scripted_model`` (Spec 005 Req 4.1) — schema-dispatched single-shot
  responses for routing / orchestrator-workers, recognised by the output
  tool's property names (``route`` → RouteDecision, ``subtasks`` →
  TaskPlan); every PydanticAI output tool is named ``final_result`` so the
  schema, not the name, selects the payload.
* the Spec 006-2a Req 7.1/7.2 turn-sequenced family — four deterministic
  modes that drive the new patterns' multi-call loops without any network
  I/O, while preserving the schema-dispatch mode above:

  - ``turn_sequenced_model`` advances by the number of ``ToolReturnPart``
    entries already in history, replaying a scripted tool-call → final
    answer sequence with a fixed per-turn token usage so the
    autonomous-agent budget seam (``ModelResponse.usage`` token sum) fires
    deterministically.
  - ``voting_model`` replays one output per call via a call cursor, so the
    parallelization ``voting`` variant can be fed a split vote (e.g. 2:1)
    even though every branch shares the same prompt.
  - ``verdict_sequenced_model`` replays an evaluator ``verdict`` vocabulary
    via a cursor (``revise → … → pass``) while answering generator text
    requests, so evaluator-optimizer ``passed`` and ``max_iterations``
    stop paths are both reachable offline.
  - ``StubTool`` is a deterministic in-memory tool implementing the
    contracts ``Tool`` Protocol, returning a canned observation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage

if TYPE_CHECKING:
    from collections.abc import Sequence

    from patterns_contracts import Tool
    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.models.function import AgentInfo

__all__ = [
    "FinalTurn",
    "StubTool",
    "ToolTurn",
    "scripted_model",
    "turn_sequenced_model",
    "verdict_sequenced_model",
    "voting_model",
]


def scripted_model(
    *,
    route_payload: dict[str, Any] | None = None,
    plan_payload: dict[str, Any] | None = None,
    text: str = "scripted-text",
    model_name: str = "fake-scripted",
) -> FunctionModel:
    """Build a ``FunctionModel`` returning canned structured/text responses.

    Args:
        route_payload: Args for a ``RouteDecision``-shaped output tool
            (its schema exposes a ``route`` property).
        plan_payload: Args for a ``TaskPlan``-shaped output tool (its
            schema exposes a ``subtasks`` property).
        text: Response for plain-text (``output_type=str``) requests.
        model_name: Identifier surfaced in instrumentation spans.

    Returns:
        A ``FunctionModel`` usable anywhere the patterns accept ``model``.

    Raises:
        AssertionError: At call time, when the agent requests a structured
            output the script has no payload for — a test-authoring error
            that should fail loudly.
    """

    def _respond(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if info.output_tools:
            tool = info.output_tools[0]
            properties: dict[str, Any] = tool.parameters_json_schema.get("properties", {})
            if "route" in properties and route_payload is not None:
                return ModelResponse(parts=[ToolCallPart(tool.name, route_payload)])
            if "subtasks" in properties and plan_payload is not None:
                return ModelResponse(parts=[ToolCallPart(tool.name, plan_payload)])
            msg = f"scripted_model has no payload for output schema: {sorted(properties)}"
            raise AssertionError(msg)
        return ModelResponse(parts=[TextPart(text)])

    return FunctionModel(_respond, model_name=model_name)


@dataclass(frozen=True)
class ToolTurn:
    """A scripted turn that invokes a tool (emits a ``ToolCallPart``).

    Args:
        tool: Tool name placed in the emitted ``ToolCallPart``.
        args: Raw string args for the call; the autonomous loop reads
            ``ToolCallPart.args`` and forwards it to ``Tool.run``.
        tokens: Token usage surfaced on this turn's ``ModelResponse`` so the
            budget seam (``usage`` token sum) can fire deterministically.
    """

    tool: str
    args: str = ""
    tokens: int = 0


@dataclass(frozen=True)
class FinalTurn:
    """A scripted turn that ends the loop with a final text answer.

    Args:
        text: Final answer text (no tool call).
        tokens: Token usage surfaced on this turn's ``ModelResponse``.
    """

    text: str
    tokens: int = 0


Turn = ToolTurn | FinalTurn
"""A single scripted turn for :func:`turn_sequenced_model`."""


def _count_tool_returns(messages: list[ModelMessage]) -> int:
    """Count ``ToolReturnPart`` entries across the whole message history.

    The count is the zero-based index of the turn the loop has reached:
    every completed tool call leaves one ``ToolReturnPart`` in history, so
    progression is independent of how the loop drives the model.
    """
    return sum(
        1 for message in messages for part in message.parts if isinstance(part, ToolReturnPart)
    )


def turn_sequenced_model(
    turns: Sequence[Turn],
    *,
    model_name: str = "fake-turns",
) -> FunctionModel:
    """Replay a scripted tool-call/final-answer sequence for tool loops.

    The turn index is the number of ``ToolReturnPart`` entries already in
    history, so the same script replays identically whether the loop is
    driven manually or by an ``Agent`` (Spec 006-2a Req 7.2).

    Args:
        turns: Ordered turns; typically several :class:`ToolTurn` followed by
            a terminal :class:`FinalTurn`.
        model_name: Identifier surfaced in instrumentation spans.

    Returns:
        A ``FunctionModel`` that emits one turn per model request.

    Raises:
        AssertionError: When the loop requests more turns than scripted — a
            test-authoring error that should fail loudly.
    """

    def _respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        index = _count_tool_returns(messages)
        if index >= len(turns):
            msg = f"turn_sequenced_model exhausted at turn {index} (have {len(turns)} turns)"
            raise AssertionError(msg)
        turn = turns[index]
        usage = RequestUsage(output_tokens=turn.tokens)
        if isinstance(turn, ToolTurn):
            return ModelResponse(parts=[ToolCallPart(turn.tool, turn.args)], usage=usage)
        return ModelResponse(parts=[TextPart(turn.text)], usage=usage)

    return FunctionModel(_respond, model_name=model_name)


def voting_model(
    branch_outputs: Sequence[str],
    *,
    tokens: int = 0,
    model_name: str = "fake-voting",
) -> FunctionModel:
    """Replay one branch output per call via a call cursor.

    The parallelization ``voting`` variant fans out the same prompt to ``n``
    branches, which would otherwise vote unanimously; this cursor lets a test
    supply a split vote (e.g. ``["a", "a", "b"]`` → 2:1). Calls are served in
    order, so the i-th branch to reach the model receives ``branch_outputs[i]``
    (Spec 006-2a Req 4.3 offline seam).

    Args:
        branch_outputs: One text output per expected model call.
        tokens: Token usage surfaced on each ``ModelResponse``.
        model_name: Identifier surfaced in instrumentation spans.

    Returns:
        A ``FunctionModel`` emitting the scripted outputs in call order.

    Raises:
        AssertionError: When called more times than outputs were scripted.
    """
    cursor = [0]

    def _respond(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        index = cursor[0]
        if index >= len(branch_outputs):
            msg = f"voting_model exhausted at call {index} (have {len(branch_outputs)} outputs)"
            raise AssertionError(msg)
        cursor[0] = index + 1
        return ModelResponse(
            parts=[TextPart(branch_outputs[index])],
            usage=RequestUsage(output_tokens=tokens),
        )

    return FunctionModel(_respond, model_name=model_name)


def verdict_sequenced_model(
    verdicts: Sequence[dict[str, Any]],
    *,
    candidate: str | Sequence[str] = "candidate",
    tokens: int = 0,
    model_name: str = "fake-verdict",
) -> FunctionModel:
    """Replay an evaluator verdict vocabulary while answering generator text.

    Evaluator-optimizer alternates a generator (plain-text candidate) with an
    evaluator (structured output exposing a ``verdict`` property). A fixed
    payload can only reproduce ``all-revise → max_iterations``; this cursor
    replays a ``revise → … → pass`` transition so the ``passed`` stop path and
    feedback reflection are both reachable offline (Spec 006-2a Req 5.3/5.4).

    Args:
        verdicts: Ordered payloads for the ``verdict``-shaped output tool
            (each typically ``{"verdict": ..., "feedback": ...}``).
        candidate: Generator text; a sequence is replayed per generator call
            (clamped to the last entry), a single string repeats.
        tokens: Token usage surfaced on each ``ModelResponse``.
        model_name: Identifier surfaced in instrumentation spans.

    Returns:
        A ``FunctionModel`` dispatching verdict vs generator by output schema.

    Raises:
        AssertionError: When more verdicts are requested than scripted, or a
            structured output without a ``verdict`` property is requested.
    """
    verdict_cursor = [0]
    gen_cursor = [0]
    candidates = [candidate] if isinstance(candidate, str) else list(candidate)

    def _respond(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        usage = RequestUsage(output_tokens=tokens)
        if info.output_tools:
            tool = info.output_tools[0]
            properties: dict[str, Any] = tool.parameters_json_schema.get("properties", {})
            if "verdict" not in properties:
                msg = f"verdict_sequenced_model: unexpected output schema {sorted(properties)}"
                raise AssertionError(msg)
            index = verdict_cursor[0]
            if index >= len(verdicts):
                msg = f"verdict_sequenced_model exhausted at verdict {index}"
                raise AssertionError(msg)
            verdict_cursor[0] = index + 1
            return ModelResponse(parts=[ToolCallPart(tool.name, verdicts[index])], usage=usage)
        index = min(gen_cursor[0], len(candidates) - 1)
        gen_cursor[0] += 1
        return ModelResponse(parts=[TextPart(candidates[index])], usage=usage)

    return FunctionModel(_respond, model_name=model_name)


@dataclass
class StubTool:
    """Deterministic in-memory tool implementing the contracts ``Tool`` Protocol.

    Args:
        name: Tool identifier matched against ``allowed_tools``.
        observation: Canned observation returned by every ``run`` call.
        dangerous: Whether the tool requires ``approval_hook`` clearance.
    """

    name: str
    observation: str = "ok"
    dangerous: bool = False

    def run(self, args: str) -> str:
        """Return the canned observation, ignoring ``args`` (deterministic)."""
        return self.observation


if TYPE_CHECKING:
    # Static guard: ``StubTool`` structurally satisfies the contracts ``Tool``
    # Protocol. pyright fails here if a field/signature ever drifts out of shape.
    _stubtool_is_tool: type[Tool] = StubTool
