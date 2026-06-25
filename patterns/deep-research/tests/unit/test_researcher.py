"""Reflect-loop digest seam tests for the sub-researcher (Spec 010 Req 1).

The sub-researcher re-injects a results digest into every reflect turn. Spec 010
makes that digest generator an injectable seam (``digest_fn``) so the reflect loop
can opt into note-based compaction (``compact_digest``) while the default stays
byte-compatible with ``_results_digest``. The *compression* turn keeps the full
``_results_digest`` regardless of the seam, preserving citation grounding (ADR-A).

These tests capture the actual prompt strings the scripted model receives, so the
byte-compatibility lock does NOT rely on ``digest_fn is _results_digest`` object
identity: it asserts the rendered reflect prompt equals an expected string built
from ``_results_digest(collected)`` (the digest is reused; the prompt assembly is
reconstructed independently in the test). This catches a regression in either the
default seam wiring or ``_results_digest`` itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from patterns_contracts import Finding, SearchResult, SubQuestion
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage

from patterns_deep_research.notes import compact_digest, distill_notes

# ``_results_digest`` is imported white-box to build the byte-compatibility lock's
# expected string from the same source the production default seam uses (Req 1.3);
# the leading-underscore name is intentional here, not an upstream defect.
from patterns_deep_research.researcher import (
    _results_digest,  # pyright: ignore[reportPrivateUsage]
    run_subquestion,
)
from tests.support.fake_search import FakeSearchProvider

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.models.function import AgentInfo

_SUBQUESTION = SubQuestion(description="How does the lead orchestrator decompose a query?")

# A tiny pre-sorted corpus (descending score, then source) so the FakeSearchProvider
# returns it unchanged and ``collected`` is byte-predictable on a reflect turn.
_RESULTS: list[SearchResult] = [
    SearchResult(source="A", locator="1", snippet="Alpha finding. Trailing detail.", score=0.9),
    SearchResult(source="B", locator="2", snippet="Beta finding. Trailing detail.", score=0.8),
]
# ``cited_sources`` must name a source present in ``collected`` so compression maps a
# real citation instead of raising EmptyCitationError / DanglingCitationError.
_FINDING: dict[str, Any] = {"summary": "Grounded summary.", "cited_sources": ["A"]}


def _user_prompt(messages: list[ModelMessage]) -> str:
    """Return the latest user-prompt text the model was asked to respond to."""
    for message in reversed(messages):
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, UserPromptPart):
                    content = part.content
                    return content if isinstance(content, str) else str(content)
    msg = "no user prompt captured in the message history"
    raise AssertionError(msg)


class _PromptCapture:
    """Scripted model that records the reflect / compression prompts it receives.

    Dispatches on the output schema like ``scripted_model`` (``enough`` -> reflect,
    ``cited_sources`` -> compression) but, instead of discarding the prompt, appends
    each turn's user-prompt text so a test can assert on the rendered digest block.
    """

    # FunctionModel derives a default name from ``function.__name__``; a callable
    # instance has none, so expose one explicitly.
    __name__ = "prompt_capture"

    def __init__(self, *, action: dict[str, Any], finding: dict[str, Any]) -> None:
        self.reflect_prompts: list[str] = []
        self.compress_prompts: list[str] = []
        self._action = action
        self._finding = finding

    def __call__(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        usage = RequestUsage(output_tokens=7)
        tool = info.output_tools[0]
        properties: dict[str, Any] = tool.parameters_json_schema.get("properties", {})
        prompt = _user_prompt(messages)
        if "enough" in properties:
            self.reflect_prompts.append(prompt)
            return ModelResponse(parts=[ToolCallPart(tool.name, self._action)], usage=usage)
        if "cited_sources" in properties:
            self.compress_prompts.append(prompt)
            return ModelResponse(parts=[ToolCallPart(tool.name, self._finding)], usage=usage)
        msg = f"_PromptCapture has no payload for output schema: {sorted(properties)}"
        raise AssertionError(msg)


def _reflect_prompt(digest: str) -> str:
    """Reconstruct the reflect-turn prompt independently of production assembly."""
    return f"Subquestion: {_SUBQUESTION.description}\n\nResults so far:\n{digest}"


def _compress_prompt(digest: str) -> str:
    """Reconstruct the compression-turn prompt independently of production assembly."""
    return f"Subquestion: {_SUBQUESTION.description}\n\nGathered results:\n{digest}"


async def _run(
    capture: _PromptCapture,
    *,
    digest_fn: Any = None,
    max_iterations: int = 2,
) -> Finding:
    """Drive ``run_subquestion`` with the capturing model and the tiny corpus."""
    model = FunctionModel(capture, model_name="prompt-capture")
    search = FakeSearchProvider(corpus=_RESULTS)
    if digest_fn is None:
        return await run_subquestion(
            _SUBQUESTION, model=model, search=search, max_iterations=max_iterations
        )
    return await run_subquestion(
        _SUBQUESTION,
        model=model,
        search=search,
        max_iterations=max_iterations,
        digest_fn=digest_fn,
    )


async def test_default_digest_fn_keeps_byte_compatible_reflect_prompt() -> None:
    # Default (no injection): the second reflect turn sees ``collected`` == _RESULTS
    # (one search of the pre-sorted corpus). Its prompt must equal the expected
    # string built from ``_results_digest`` — a byte-compat lock independent of
    # function identity.
    capture = _PromptCapture(action={"query": "keep going", "enough": False}, finding=_FINDING)
    await _run(capture)
    assert capture.reflect_prompts[1] == _reflect_prompt(_results_digest(_RESULTS))


async def test_injected_compact_digest_drives_the_reflect_prompt() -> None:
    # Injecting ``compact_digest`` swaps the reflect-turn results block to the
    # note-compacted notebook, and it must differ from the full digest.
    capture = _PromptCapture(action={"query": "keep going", "enough": False}, finding=_FINDING)
    await _run(capture, digest_fn=compact_digest)
    assert capture.reflect_prompts[1] == _reflect_prompt(compact_digest(_RESULTS))
    assert capture.reflect_prompts[1] != _reflect_prompt(_results_digest(_RESULTS))


async def test_compression_turn_keeps_the_full_results_digest() -> None:
    # Even with ``compact_digest`` injected for reflect, the compression turn keeps
    # the full ``_results_digest`` block (citation grounding, ADR-A). enough=True on
    # the first turn -> one search -> ``collected`` == _RESULTS at compression.
    capture = _PromptCapture(action={"query": "go", "enough": True}, finding=_FINDING)
    await _run(capture, digest_fn=compact_digest, max_iterations=3)
    assert capture.compress_prompts[0] == _compress_prompt(_results_digest(_RESULTS))
    assert capture.compress_prompts[0] != _compress_prompt(compact_digest(_RESULTS))


async def test_finding_carries_distilled_notes_with_default_digest() -> None:
    # The handoff (Req 2.2) carries distilled notes, not the raw transcript: after
    # the loop, ``Finding.notes`` equals ``distill_notes(collected)`` — here the
    # single search of the pre-sorted corpus, so ``collected`` == _RESULTS.
    capture = _PromptCapture(action={"query": "go", "enough": True}, finding=_FINDING)
    finding = await _run(capture)
    assert finding.notes == distill_notes(_RESULTS)
    assert finding.notes  # filled, not the empty contract default


async def test_finding_notes_filled_independent_of_injected_digest() -> None:
    # Notes are distilled from ``collected`` itself, so the reflect ``digest_fn`` seam
    # does not change them: injecting ``compact_digest`` yields the same notes.
    capture = _PromptCapture(action={"query": "go", "enough": True}, finding=_FINDING)
    finding = await _run(capture, digest_fn=compact_digest)
    assert finding.notes == distill_notes(_RESULTS)


async def test_empty_collected_hands_off_nothing_and_notes_default_empty() -> None:
    # When nothing is gathered the loud-fail citation guard fires before a Finding is
    # handed off, so an empty-collected handoff never leaks a raw transcript. The
    # notes value the seam would carry for empty input is the safe ``[]`` default.
    from patterns_deep_research import EmptyCitationError

    capture = _PromptCapture(
        action={"query": "", "enough": True},
        finding={"summary": "no search performed", "cited_sources": []},
    )
    model = FunctionModel(capture, model_name="prompt-capture")
    with pytest.raises(EmptyCitationError):
        await run_subquestion(
            _SUBQUESTION, model=model, search=FakeSearchProvider(), max_iterations=1
        )
    assert distill_notes([]) == []
