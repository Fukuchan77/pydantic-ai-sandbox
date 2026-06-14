"""Scripted ``ChatModel`` fakes for deterministic offline tests.

beeai-framework ships no official mock (upstream issue #750); its own test
suite subclasses ``ChatModel`` directly (e.g. ``ReverseWordsDummyModel``),
so these fakes follow the same approach (research.md R-4). They implement
the abstract surface of beeai-framework 0.1.39 — ``_create``,
``_create_stream``, ``_create_structure``, ``model_id``, ``provider_id``.
Because that surface is internal, the lane pins beeai-framework EXACT
(``==``) and the smoke test guards drift (plan §8 R-1).

This module carries two generations of fakes, mirroring the pydantic-ai
lane's ``model_fakes.py`` (Spec 006-2a Req 7.1/7.2):

* ``ScriptedChatModel`` (Spec 005 Req 4.1) — schema-dispatched single-shot
  responses for routing / orchestrator-workers. ``_create_structure`` keys
  off the requested schema's fields: a ``route`` field gets ``route_payload``,
  a ``subtasks`` field gets ``plan_payload``; plain chat gets ``text``.
* the Spec 006-2a turn-sequenced family — three deterministic models plus an
  in-memory tool stub that drive the new patterns' multi-call loops with no
  network I/O. Unlike the pydantic-ai lane (which counts ``ToolReturnPart``
  entries in history), beeai exposes no such history at the model boundary, so
  each model advances by an internal **call cursor** incremented on every
  ``_create`` / ``_create_structure`` invocation (plan line 165 difference):

  - ``TurnSequencedChatModel`` replays a scripted tool-call → final-answer
    sequence, emitting a ``MessageToolCallContent`` for each :class:`ToolTurn`
    and plain text for the terminal :class:`FinalTurn`, with a fixed per-turn
    ``ChatModelUsage.total_tokens`` so the autonomous-agent budget seam fires
    deterministically.
  - ``VotingChatModel`` replays one branch output per call, so the
    parallelization ``voting`` variant can be fed a split vote (e.g. 2:1) even
    though every branch shares the same prompt.
  - ``VerdictSequencedChatModel`` answers generator text via ``_create`` (a
    candidate cursor) and evaluator verdicts via ``_create_structure`` (a
    verdict cursor), so evaluator-optimizer ``passed`` and ``max_iterations``
    stop paths are both reachable offline. Dispatch is by *method* (generate
    vs. evaluate), not by output schema shape.
  - ``StubTool`` is a deterministic in-memory tool implementing the contracts
    ``Tool`` Protocol, returning a canned observation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from beeai_framework.backend.chat import ChatModel
from beeai_framework.backend.message import AssistantMessage, MessageToolCallContent
from beeai_framework.backend.types import (
    ChatModelOutput,
    ChatModelStructureOutput,
    ChatModelUsage,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Sequence

    from beeai_framework.backend.constants import ProviderName
    from beeai_framework.backend.types import ChatModelInput, ChatModelStructureInput
    from beeai_framework.context import RunContext
    from patterns_contracts import Tool

__all__ = [
    "FinalTurn",
    "ScriptedChatModel",
    "StubTool",
    "ToolTurn",
    "TurnSequencedChatModel",
    "VerdictSequencedChatModel",
    "VotingChatModel",
]


def _usage(tokens: int) -> ChatModelUsage:
    """Build a deterministic usage record surfacing ``tokens`` as the total.

    The autonomous-agent budget seam reads ``ChatModelOutput.usage.total_tokens``;
    a single completion-token figure keeps the three usage fields consistent.
    """
    return ChatModelUsage(prompt_tokens=0, completion_tokens=tokens, total_tokens=tokens)


class _BaseScriptedChatModel(ChatModel):
    """Shared identifiers and stream delegation for the scripted fakes.

    Concrete fakes implement only ``_create`` (and ``_create_structure`` when
    they script structured output); the streaming path delegates to ``_create``
    so a single ``create`` call advances any internal cursor exactly once,
    regardless of whether streaming is requested.
    """

    @property
    def model_id(self) -> str:
        """Fake model identifier (surfaced in emitter metadata)."""
        return "scripted-fake"

    @property
    def provider_id(self) -> ProviderName:
        """Provider identifier; constrained upstream to the ProviderName Literal.

        "ollama" is borrowed purely to satisfy the closed vocabulary — no
        Ollama daemon is ever contacted (``_create*`` are all canned).
        """
        return "ollama"

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
        """Reject structured output by default; verdict/schema fakes override.

        Raising loudly surfaces a test-authoring error (a structured request
        sent to a fake that scripts only text).
        """
        del input, run
        msg = f"{type(self).__name__} does not script structured output"
        raise AssertionError(msg)


class ScriptedChatModel(_BaseScriptedChatModel):
    """Network-free ``ChatModel`` returning canned structured/text responses."""

    def __init__(
        self,
        *,
        route_payload: dict[str, Any] | None = None,
        plan_payload: dict[str, Any] | None = None,
        text: str = "scripted-text",
    ) -> None:
        """Store the canned payloads; no I/O happens at any point."""
        super().__init__()
        self._route_payload = route_payload
        self._plan_payload = plan_payload
        self._text = text

    async def _create(self, input: ChatModelInput, run: RunContext) -> ChatModelOutput:  # noqa: A002 - upstream signature
        del input, run
        return ChatModelOutput(messages=[AssistantMessage(self._text)])

    async def _create_structure(
        self,
        input: ChatModelStructureInput[Any],  # noqa: A002 - upstream signature
        run: RunContext,
    ) -> ChatModelStructureOutput:
        del run
        schema = input.input_schema
        field_names = set(getattr(schema, "model_fields", {}))
        if "route" in field_names and self._route_payload is not None:
            return ChatModelStructureOutput(object=self._route_payload)
        if "subtasks" in field_names and self._plan_payload is not None:
            return ChatModelStructureOutput(object=self._plan_payload)
        msg = f"ScriptedChatModel has no payload for schema fields: {sorted(field_names)}"
        raise AssertionError(msg)


@dataclass(frozen=True)
class ToolTurn:
    """A scripted turn that invokes a tool (emits a ``MessageToolCallContent``).

    Args:
        tool: Tool name placed in the emitted tool-call content; the autonomous
            loop matches it against ``allowed_tools`` and forwards ``args``.
        args: Raw string args for the call.
        tokens: Token usage surfaced on this turn's ``ChatModelOutput`` so the
            budget seam (``usage.total_tokens``) can fire deterministically.
    """

    tool: str
    args: str = ""
    tokens: int = 0


@dataclass(frozen=True)
class FinalTurn:
    """A scripted turn that ends the loop with a final text answer.

    Args:
        text: Final answer text (no tool call).
        tokens: Token usage surfaced on this turn's ``ChatModelOutput``.
    """

    text: str
    tokens: int = 0


Turn = ToolTurn | FinalTurn
"""A single scripted turn for :class:`TurnSequencedChatModel`."""


class TurnSequencedChatModel(_BaseScriptedChatModel):
    """Replay a scripted tool-call/final-answer sequence for tool loops.

    Each ``create`` call advances an internal cursor and returns the next turn,
    so the same script replays identically across a manual loop or a Workflow
    (Spec 006-2a Req 7.2). A :class:`ToolTurn` emits an ``AssistantMessage``
    carrying a ``MessageToolCallContent``; a :class:`FinalTurn` emits plain text.

    Raises:
        AssertionError: When the loop requests more turns than scripted — a
            test-authoring error that should fail loudly.
    """

    def __init__(self, turns: Sequence[Turn]) -> None:
        """Store the scripted turns; the call cursor starts at zero."""
        super().__init__()
        self._turns = list(turns)
        self._cursor = 0

    async def _create(self, input: ChatModelInput, run: RunContext) -> ChatModelOutput:  # noqa: A002 - upstream signature
        del input, run
        index = self._cursor
        if index >= len(self._turns):
            msg = (
                f"TurnSequencedChatModel exhausted at turn {index} (have {len(self._turns)} turns)"
            )
            raise AssertionError(msg)
        self._cursor = index + 1
        turn = self._turns[index]
        usage = _usage(turn.tokens)
        if isinstance(turn, ToolTurn):
            call = MessageToolCallContent(id=f"call-{index}", tool_name=turn.tool, args=turn.args)
            return ChatModelOutput(messages=[AssistantMessage([call])], usage=usage)
        return ChatModelOutput(messages=[AssistantMessage(turn.text)], usage=usage)


class VotingChatModel(_BaseScriptedChatModel):
    """Replay one branch output per call via a call cursor.

    The parallelization ``voting`` variant fans out the same prompt to ``n``
    branches, which would otherwise vote unanimously; this cursor lets a test
    supply a split vote (e.g. ``["a", "a", "b"]`` → 2:1). Outputs are served in
    call order, so the i-th branch to reach the model receives
    ``branch_outputs[i]``; mapping that call order back onto branch indices is
    the consumer's responsibility (Task 6.2, Spec 006-2a Req 4.3 offline seam).

    Raises:
        AssertionError: When called more times than outputs were scripted.
    """

    def __init__(self, branch_outputs: Sequence[str], *, tokens: int = 0) -> None:
        """Store the per-call outputs; the call cursor starts at zero."""
        super().__init__()
        self._outputs = list(branch_outputs)
        self._tokens = tokens
        self._cursor = 0

    async def _create(self, input: ChatModelInput, run: RunContext) -> ChatModelOutput:  # noqa: A002 - upstream signature
        del input, run
        index = self._cursor
        if index >= len(self._outputs):
            msg = f"VotingChatModel exhausted at call {index} (have {len(self._outputs)} outputs)"
            raise AssertionError(msg)
        self._cursor = index + 1
        return ChatModelOutput(
            messages=[AssistantMessage(self._outputs[index])],
            usage=_usage(self._tokens),
        )


class VerdictSequencedChatModel(_BaseScriptedChatModel):
    """Replay generator text and an evaluator verdict vocabulary by call cursor.

    Evaluator-optimizer alternates a generator (plain-text candidate via
    ``create``) with an evaluator (structured verdict via ``create_structure``).
    A fixed payload can only reproduce ``all-revise → max_iterations``; the two
    cursors replay a ``revise → … → pass`` transition so the ``passed`` stop
    path and feedback reflection are both reachable offline (Spec 006-2a
    Req 5.3/5.4). Dispatch is by method, not output schema shape, so it is
    robust to the evaluator schema settling in Task 7.

    Raises:
        AssertionError: When more verdicts are requested than scripted.
    """

    def __init__(
        self,
        verdicts: Sequence[dict[str, Any]],
        *,
        candidate: str | Sequence[str] = "candidate",
        tokens: int = 0,
    ) -> None:
        """Store verdict payloads and generator candidate(s); cursors start at zero."""
        super().__init__()
        self._verdicts = list(verdicts)
        self._candidates = [candidate] if isinstance(candidate, str) else list(candidate)
        self._tokens = tokens
        self._verdict_cursor = 0
        self._gen_cursor = 0

    async def _create(self, input: ChatModelInput, run: RunContext) -> ChatModelOutput:  # noqa: A002 - upstream signature
        del input, run
        index = min(self._gen_cursor, len(self._candidates) - 1)
        self._gen_cursor += 1
        return ChatModelOutput(
            messages=[AssistantMessage(self._candidates[index])],
            usage=_usage(self._tokens),
        )

    async def _create_structure(
        self,
        input: ChatModelStructureInput[Any],  # noqa: A002 - upstream signature
        run: RunContext,
    ) -> ChatModelStructureOutput:
        del input, run
        index = self._verdict_cursor
        if index >= len(self._verdicts):
            msg = f"VerdictSequencedChatModel exhausted at verdict {index}"
            raise AssertionError(msg)
        self._verdict_cursor = index + 1
        return ChatModelStructureOutput(object=self._verdicts[index])


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
