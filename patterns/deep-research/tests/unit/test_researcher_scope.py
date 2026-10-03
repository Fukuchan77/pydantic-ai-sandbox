"""Tests for the sub-researcher scope block (Spec 009 Req 3/7 follow-up).

``orchestrator.py``'s module docstring calls ``ResearchBrief.out_of_scope`` "the
explicit-exclusion seam that keeps the parallel sub-researchers from drifting onto
each other's ground" -- but ``run_subquestion`` previously received only the
``SubQuestion``, never the brief, so that seam was declared and never actually
wired to any prompt. These tests cover the fix: ``_scope_block`` in isolation, and
``run_subquestion(..., brief=...)`` end to end via a prompt-capturing model.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from patterns_contracts import Finding, ResearchBrief, SearchResult, SubQuestion
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage

from patterns_deep_research.researcher import (
    _scope_block,  # pyright: ignore[reportPrivateUsage]
    run_subquestion,
)
from tests.support.fake_search import FakeSearchProvider

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.models.function import AgentInfo

_SUBQUESTION = SubQuestion(description="How does the lead orchestrator decompose a query?")
_RESULTS: list[SearchResult] = [
    SearchResult(source="A", locator="1", snippet="Alpha finding.", score=0.9),
]
_FINDING: dict[str, Any] = {"summary": "Grounded summary.", "cited_sources": ["A"]}


class TestScopeBlockRendering:
    """``_scope_block`` in isolation -- no model, no I/O."""

    def test_none_renders_as_empty_string(self) -> None:
        """Byte-compatibility: an un-opted caller sees no prefix at all."""
        assert _scope_block(None) == ""

    def test_renders_objective_and_bulleted_exclusions(self) -> None:
        brief = ResearchBrief(
            query="q",
            objective="Cover A and B.",
            out_of_scope=["pricing details", "unreleased features"],
        )
        block = _scope_block(brief)
        assert "Cover A and B." in block
        assert "- pricing details" in block
        assert "- unreleased features" in block
        # Ends with a blank line so it composes cleanly with the subquestion line.
        assert block.endswith("\n\n")

    def test_empty_out_of_scope_renders_a_placeholder_not_a_blank_list(self) -> None:
        brief = ResearchBrief(query="q", objective="Cover A.", out_of_scope=[])
        block = _scope_block(brief)
        assert "(none)" in block


def _user_prompt(messages: list[ModelMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, UserPromptPart):
                    content = part.content
                    return content if isinstance(content, str) else str(content)
    msg = "no user prompt captured in the message history"
    raise AssertionError(msg)


class _PromptCapture:
    """Scripted model recording the reflect/compression prompts it receives."""

    __name__ = "scope_prompt_capture"

    def __init__(self, *, action: dict[str, Any], finding: dict[str, Any]) -> None:
        self.reflect_prompts: list[str] = []
        self.compress_prompts: list[str] = []
        self._action = action
        self._finding = finding

    def __call__(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        usage = RequestUsage(output_tokens=1)
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


class TestRunSubquestionForwardsScope:
    """``run_subquestion(..., brief=...)`` end to end via a real (scripted) agent run."""

    async def test_scope_block_prefixes_both_reflect_and_compression_prompts(self) -> None:
        brief = ResearchBrief(
            query="q",
            objective="Cover multi-agent trade-offs.",
            out_of_scope=["single-agent baselines"],
        )
        capture = _PromptCapture(action={"query": "go", "enough": True}, finding=_FINDING)
        model = FunctionModel(capture, model_name="scope-capture")
        search = FakeSearchProvider(corpus=_RESULTS)

        finding = await run_subquestion(
            _SUBQUESTION,
            model=model,
            search=search,
            max_iterations=2,
            brief=brief,
        )

        assert isinstance(finding, Finding)
        expected_scope = _scope_block(brief)
        assert expected_scope  # sanity: non-empty for a real brief
        assert capture.reflect_prompts[0].startswith(expected_scope)
        assert capture.compress_prompts[0].startswith(expected_scope)
        assert "single-agent baselines" in capture.reflect_prompts[0]
        assert "single-agent baselines" in capture.compress_prompts[0]

    async def test_no_brief_keeps_the_prompt_byte_identical_to_before(self) -> None:
        """Backward compatibility: an un-opted direct caller sees no scope block."""
        capture = _PromptCapture(action={"query": "go", "enough": True}, finding=_FINDING)
        model = FunctionModel(capture, model_name="no-scope-capture")
        search = FakeSearchProvider(corpus=_RESULTS)

        await run_subquestion(
            _SUBQUESTION,
            model=model,
            search=search,
            max_iterations=2,
        )

        assert capture.reflect_prompts[0] == (
            f"Subquestion: {_SUBQUESTION.description}\n\nResults so far:\n(no results gathered yet)"
        )
