"""Scripted ``CustomLLM`` fakes for deterministic offline tests.

``llama_index.core.llms.MockLLM`` echoes prompts / emits filler tokens and
cannot produce schema-valid JSON, so structured-output steps need a scripted
fake (research.md R-4). These fakes are ``CustomLLM`` subclasses (plain
completion models, NOT function-calling): ``astructured_predict`` therefore
exercises the text-completion program path, whose JSON output parser validates
the canned response against the contract model — the same validation surface the
live function-calling path lands on. ``acomplete`` / ``achat`` / ``apredict`` are
derived by ``CustomLLM`` from the sync ``complete``, so a single completion seam
drives every entry point.

This module carries two generations of fakes, mirroring the pydantic-ai and beeai
lanes (Spec 006-2a Req 7.1/7.2):

* ``ScriptedLLM`` (Spec 005 Req 4.1) — schema-dispatched single-shot responses
  for routing / orchestrator-workers. The structured-predict prompt embeds the
  output schema, so the schema's distinctive property name (``"route"`` /
  ``"subtasks"``) appearing in the prompt selects the structured payload;
  everything else gets the plain ``text`` response. Test inputs must avoid those
  two quoted tokens.
* the Spec 006-2a turn-sequenced family — three deterministic models plus an
  in-memory tool stub that drive the new patterns' multi-call loops with no
  network I/O. Like the beeai lane (and unlike pydantic-ai, which counts
  ``ToolReturnPart`` entries in history), LlamaIndex exposes no tool-return
  history at the model boundary, so each model advances by an internal **call
  cursor** incremented on every ``complete`` invocation (plan line 165
  difference):

  - ``TurnSequencedLLM`` replays a scripted tool-call → final-answer sequence,
    emitting a ``{"tool": ..., "args": ...}`` JSON action for each
    :class:`ToolTurn` and plain text for the terminal :class:`FinalTurn`, with a
    fixed per-turn token count on ``CompletionResponse.raw`` so the
    autonomous-agent budget seam fires deterministically.
  - ``VotingLLM`` replays one branch output per call, so the parallelization
    ``voting`` variant can be fed a split vote (e.g. 2:1) even though every
    branch shares the same prompt.
  - ``VerdictSequencedLLM`` answers generator text and evaluator verdicts that
    both arrive through ``complete``; the quoted ``"verdict"`` token in a
    structured-predict prompt selects the verdict cursor, so evaluator-optimizer
    ``passed`` and ``max_iterations`` stop paths are both reachable offline.
  - ``StubTool`` is a deterministic in-memory tool implementing the contracts
    ``Tool`` Protocol, returning a canned observation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

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
from pydantic import PrivateAttr

if TYPE_CHECKING:
    from collections.abc import Sequence

    from patterns_contracts import Tool

__all__ = [
    "FinalTurn",
    "ScriptedLLM",
    "StubTool",
    "ToolTurn",
    "TurnSequencedLLM",
    "VerdictSequencedLLM",
    "VotingLLM",
]


def _raw_usage(tokens: int) -> dict[str, Any]:
    """Build the ``CompletionResponse.raw`` payload the budget seam reads.

    The autonomous-agent ``_budget_spent`` seam (Task 8.3) reads
    ``CompletionResponse.raw["usage"]["total_tokens"]``; surfacing a single
    completion-token figure keeps offline budget accounting deterministic
    (plan §autonomous-agent budget seam).
    """
    return {"usage": {"total_tokens": tokens}}


def _tool_call_text(tool: str, args: str) -> str:
    """Encode a tool call as the JSON action the autonomous loop parses.

    LlamaIndex ``CustomLLM`` is completion-only (no native tool-call parts), so a
    :class:`ToolTurn` surfaces as a JSON object ``{"tool": ..., "args": ...}`` in
    the completion text; a :class:`FinalTurn` surfaces as plain text. The Task 8.3
    autonomous loop treats a completion that parses to an object carrying a
    ``"tool"`` key as a tool call and anything else as the final answer.
    """
    return json.dumps({"tool": tool, "args": args})


class _BaseScriptedLLM(CustomLLM):
    """Shared metadata and stream delegation for the scripted completion fakes.

    Concrete fakes implement only ``complete``; ``stream_complete`` delegates to
    it so a single ``complete`` / ``acomplete`` call advances any internal cursor
    exactly once, whether or not streaming is requested. ``CustomLLM`` derives the
    async and chat entry points (``acomplete`` / ``achat`` / ``apredict`` /
    ``astructured_predict``) from these sync methods, so structured prediction's
    text-completion program lands in ``complete`` too.
    """

    @property
    def metadata(self) -> LLMMetadata:
        """Advertise a plain (non-function-calling) completion model."""
        return LLMMetadata(model_name="scripted-fake", is_function_calling_model=False)

    @llm_completion_callback()  # pyright: ignore[reportUntypedFunctionDecorator]
    def stream_complete(
        self, prompt: str, formatted: bool = False, **kwargs: Any
    ) -> CompletionResponseGen:
        """Stream the single canned completion as one chunk."""
        del formatted, kwargs

        def _gen() -> CompletionResponseGen:
            yield self.complete(prompt)

        return _gen()


class ScriptedLLM(_BaseScriptedLLM):
    """Completion-only LLM returning canned structured/text responses."""

    route_payload: dict[str, Any] | None = None
    plan_payload: dict[str, Any] | None = None
    text: str = "scripted-text"

    def _dispatch(self, prompt: str) -> str:
        if '"route"' in prompt and self.route_payload is not None:
            return json.dumps(self.route_payload)
        if '"subtasks"' in prompt and self.plan_payload is not None:
            return json.dumps(self.plan_payload)
        return self.text

    @llm_completion_callback()  # pyright: ignore[reportUntypedFunctionDecorator]
    def complete(self, prompt: str, formatted: bool = False, **kwargs: Any) -> CompletionResponse:
        """Return the scripted response for ``prompt``."""
        del formatted, kwargs
        return CompletionResponse(text=self._dispatch(prompt))


@dataclass(frozen=True)
class ToolTurn:
    """A scripted turn that invokes a tool (emits a JSON tool-call action).

    Args:
        tool: Tool name placed in the emitted ``{"tool": ...}`` action; the
            autonomous loop matches it against ``allowed_tools`` and forwards
            ``args``.
        args: Raw string args for the call.
        tokens: Token count surfaced on this turn's ``CompletionResponse.raw`` so
            the budget seam (``raw["usage"]["total_tokens"]``) can fire
            deterministically.
    """

    tool: str
    args: str = ""
    tokens: int = 0


@dataclass(frozen=True)
class FinalTurn:
    """A scripted turn that ends the loop with a final text answer.

    Args:
        text: Final answer text (no tool call).
        tokens: Token count surfaced on this turn's ``CompletionResponse.raw``.
    """

    text: str
    tokens: int = 0


type Turn = ToolTurn | FinalTurn
"""A single scripted turn for :class:`TurnSequencedLLM`.

A ``type`` alias (not a bare ``X | Y`` value) so pyright resolves ``list[Turn]``
in the :class:`TurnSequencedLLM` ``PrivateAttr`` declaration as a fully-known type.
"""


class TurnSequencedLLM(_BaseScriptedLLM):
    """Replay a scripted tool-call/final-answer sequence for tool loops.

    Each ``complete`` call advances an internal **call cursor** (LlamaIndex
    exposes no tool-return history at the model boundary, unlike the pydantic-ai
    lane — plan line 165) and returns the next turn, so the same script replays
    identically across a manual autonomous loop (Spec 006-2a Req 7.2). A
    :class:`ToolTurn` emits a ``{"tool": ..., "args": ...}`` JSON action; a
    :class:`FinalTurn` emits plain text. Each turn's ``tokens`` ride on
    ``CompletionResponse.raw`` so the autonomous-agent budget seam fires
    deterministically.

    Raises:
        AssertionError: When the loop requests more turns than scripted — a
            test-authoring error that should fail loudly.
    """

    # Typed ``default_factory`` (``list[Turn]``, not bare ``list``): LlamaIndex's
    # ``CustomLLM`` ships loose stubs, through which pyright degrades a bare
    # ``list`` factory to ``list[Unknown]`` on the PrivateAttr — the explicit
    # element type keeps the declaration fully-known under strict.
    _turns: list[Turn] = PrivateAttr(default_factory=list[Turn])
    _cursor: int = PrivateAttr(default=0)

    def __init__(self, turns: Sequence[Turn]) -> None:
        """Store the scripted turns; the call cursor starts at zero."""
        super().__init__()
        self._turns = list(turns)

    @llm_completion_callback()  # pyright: ignore[reportUntypedFunctionDecorator]
    def complete(self, prompt: str, formatted: bool = False, **kwargs: Any) -> CompletionResponse:
        """Return the next scripted turn, advancing the call cursor."""
        del prompt, formatted, kwargs
        index = self._cursor
        if index >= len(self._turns):
            msg = f"TurnSequencedLLM exhausted at turn {index} (have {len(self._turns)} turns)"
            raise AssertionError(msg)
        self._cursor = index + 1
        turn = self._turns[index]
        raw = _raw_usage(turn.tokens)
        if isinstance(turn, ToolTurn):
            return CompletionResponse(text=_tool_call_text(turn.tool, turn.args), raw=raw)
        return CompletionResponse(text=turn.text, raw=raw)


class VotingLLM(_BaseScriptedLLM):
    """Replay one branch output per call via a call cursor.

    The parallelization ``voting`` variant fans out the same prompt to ``n``
    branches, which would otherwise vote unanimously; this cursor lets a test
    supply a split vote (e.g. ``["a", "a", "b"]`` → 2:1). Outputs are served in
    call order, so the i-th branch to reach the model receives
    ``branch_outputs[i]``; mapping that call order back onto branch indices is the
    consumer's responsibility (Task 6.3, Spec 006-2a Req 4.3 offline seam).

    Raises:
        AssertionError: When called more times than outputs were scripted.
    """

    _outputs: list[str] = PrivateAttr(default_factory=list[str])
    _tokens: int = PrivateAttr(default=0)
    _cursor: int = PrivateAttr(default=0)

    def __init__(self, branch_outputs: Sequence[str], *, tokens: int = 0) -> None:
        """Store the per-call outputs; the call cursor starts at zero."""
        super().__init__()
        self._outputs = list(branch_outputs)
        self._tokens = tokens

    @llm_completion_callback()  # pyright: ignore[reportUntypedFunctionDecorator]
    def complete(self, prompt: str, formatted: bool = False, **kwargs: Any) -> CompletionResponse:
        """Return the next scripted branch output, advancing the call cursor."""
        del prompt, formatted, kwargs
        index = self._cursor
        if index >= len(self._outputs):
            msg = f"VotingLLM exhausted at call {index} (have {len(self._outputs)} outputs)"
            raise AssertionError(msg)
        self._cursor = index + 1
        return CompletionResponse(text=self._outputs[index], raw=_raw_usage(self._tokens))


class VerdictSequencedLLM(_BaseScriptedLLM):
    """Replay generator text and an evaluator verdict vocabulary by prompt dispatch.

    Evaluator-optimizer alternates a generator (plain-text candidate via
    ``apredict`` / ``acomplete``) with an evaluator (structured verdict via
    ``astructured_predict`` → text-completion program). Both land in ``complete``;
    dispatch is by prompt content — a structured-predict prompt embeds the output
    schema, so the quoted ``"verdict"`` token selects the verdict cursor (the same
    heuristic ``ScriptedLLM`` uses for ``"route"`` / ``"subtasks"``, and the
    analogue of the pydantic-ai lane's schema-property dispatch). The two cursors
    replay a ``revise → … → pass`` transition so the ``passed`` stop path and
    feedback reflection are both reachable offline (Spec 006-2a Req 5.3/5.4).

    Generator test inputs must avoid the quoted ``"verdict"`` token.

    Raises:
        AssertionError: When more verdicts are requested than scripted.
    """

    # Verdicts are stored as ``dict[str, object]`` (not ``dict[str, Any]``), and
    # both lists use a typed ``default_factory``: LlamaIndex's loose ``CustomLLM``
    # stubs otherwise degrade a bare ``list`` factory (and ``Any`` elements) to
    # ``Unknown`` on the PrivateAttr under pyright strict. Callers pass concrete
    # JSON-shaped dicts which assign cleanly.
    _verdicts: list[dict[str, object]] = PrivateAttr(default_factory=list[dict[str, object]])
    _candidates: list[str] = PrivateAttr(default_factory=list[str])
    _tokens: int = PrivateAttr(default=0)
    _verdict_cursor: int = PrivateAttr(default=0)
    _gen_cursor: int = PrivateAttr(default=0)

    def __init__(
        self,
        verdicts: Sequence[dict[str, object]],
        *,
        candidate: str | Sequence[str] = "candidate",
        tokens: int = 0,
    ) -> None:
        """Store verdict payloads and generator candidate(s); cursors start at zero."""
        super().__init__()
        self._verdicts = list(verdicts)
        self._candidates = [candidate] if isinstance(candidate, str) else list(candidate)
        self._tokens = tokens

    @llm_completion_callback()  # pyright: ignore[reportUntypedFunctionDecorator]
    def complete(self, prompt: str, formatted: bool = False, **kwargs: Any) -> CompletionResponse:
        """Dispatch a verdict (structured prompt) or generator candidate by content."""
        del formatted, kwargs
        raw = _raw_usage(self._tokens)
        if '"verdict"' in prompt:
            index = self._verdict_cursor
            if index >= len(self._verdicts):
                msg = f"VerdictSequencedLLM exhausted at verdict {index}"
                raise AssertionError(msg)
            self._verdict_cursor = index + 1
            return CompletionResponse(text=json.dumps(self._verdicts[index]), raw=raw)
        index = min(self._gen_cursor, len(self._candidates) - 1)
        self._gen_cursor += 1
        return CompletionResponse(text=self._candidates[index], raw=raw)


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
