"""End-to-end digest seam propagation tests for ``run_deep_research`` (Spec 010 Req 1.1-1.2).

``run_deep_research`` threads the reflect-loop digest seam down to every
sub-researcher. These tests run the full pipeline with a prompt-capturing model and
assert the top-level ``digest_fn`` reaches a sub-researcher's reflect prompt: the
default stays byte-compatible with ``_results_digest`` (current behaviour) and
injecting ``compact_digest`` propagates the note-based compaction end to end (opt-in).

The reflect prompt string is captured from the scripted model, so the assertions do
not rely on ``digest_fn`` object identity — they compare against an expected string
built from ``_results_digest`` / ``compact_digest`` of the gathered results.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from patterns_contracts import SearchResult
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage

from patterns_deep_research import run_deep_research
from patterns_deep_research.notes import compact_digest

# White-box import to build the default-seam expected string from the same source the
# researcher's reflect loop uses (Req 1.3); the leading-underscore name is intentional.
from patterns_deep_research.researcher import _results_digest  # pyright: ignore[reportPrivateUsage]
from tests.support.fake_search import FakeSearchProvider
from tests.support.model_fakes import plan_payload

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.models.function import AgentInfo

_SUBQ = "How does the lead orchestrator decompose a query?"

# A tiny pre-sorted corpus (descending score, then source) so the FakeSearchProvider
# returns it unchanged and the second reflect turn's ``collected`` is byte-predictable.
_RESULTS: list[SearchResult] = [
    SearchResult(source="A", locator="1", snippet="Alpha finding. Trailing detail.", score=0.9),
    SearchResult(source="B", locator="2", snippet="Beta finding. Trailing detail.", score=0.8),
]
# ``cited_sources`` names a source present in ``collected`` so compression grounds it.
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


class _PipelineCapture:
    """Scripted full-pipeline model that records each sub-researcher reflect prompt.

    Dispatches on the output schema (``subquestions`` -> plan, ``enough`` -> reflect,
    ``cited_sources`` -> compression, plain text -> report) and appends the reflect
    turn's user prompt so a test can assert which digest reached the sub-researcher.
    """

    # FunctionModel derives a default name from ``function.__name__``; a callable
    # instance has none, so expose one explicitly.
    __name__ = "pipeline_capture"

    def __init__(
        self,
        *,
        plan: dict[str, Any],
        action: dict[str, Any],
        finding: dict[str, Any],
        text: str = "A synthesised report.",
    ) -> None:
        self.reflect_prompts: list[str] = []
        self._plan = plan
        self._action = action
        self._finding = finding
        self._text = text

    def __call__(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        usage = RequestUsage(output_tokens=7)
        if info.output_tools:
            tool = info.output_tools[0]
            props: dict[str, Any] = tool.parameters_json_schema.get("properties", {})
            if "subquestions" in props:
                return ModelResponse(parts=[ToolCallPart(tool.name, self._plan)], usage=usage)
            if "enough" in props:
                self.reflect_prompts.append(_user_prompt(messages))
                return ModelResponse(parts=[ToolCallPart(tool.name, self._action)], usage=usage)
            if "cited_sources" in props:
                return ModelResponse(parts=[ToolCallPart(tool.name, self._finding)], usage=usage)
            msg = f"_PipelineCapture has no payload for output schema: {sorted(props)}"
            raise AssertionError(msg)
        return ModelResponse(parts=[TextPart(self._text)], usage=usage)


def _reflect_prompt(digest: str) -> str:
    """Reconstruct the sub-researcher reflect prompt independently of production."""
    return f"Subquestion: {_SUBQ}\n\nResults so far:\n{digest}"


async def _run_pipeline(capture: _PipelineCapture, *, digest_fn: Any = None) -> None:
    """Run the full pipeline (one sub-researcher, two reflect turns) with the corpus."""
    model = FunctionModel(capture, model_name="pipeline-capture")
    search = FakeSearchProvider(corpus=_RESULTS)
    if digest_fn is None:
        await run_deep_research(
            "q", model=model, search=search, max_researchers=1, max_iterations=2
        )
    else:
        await run_deep_research(
            "q",
            model=model,
            search=search,
            max_researchers=1,
            max_iterations=2,
            digest_fn=digest_fn,
        )


async def test_default_digest_propagates_results_digest_end_to_end() -> None:
    # No injection: the sub-researcher's second reflect turn (collected == _RESULTS)
    # uses the full ``_results_digest`` — the current end-to-end behaviour.
    capture = _PipelineCapture(
        plan=plan_payload([_SUBQ]), action={"query": "go", "enough": False}, finding=_FINDING
    )
    await _run_pipeline(capture)
    assert capture.reflect_prompts[1] == _reflect_prompt(_results_digest(_RESULTS))


async def test_injected_compact_digest_propagates_end_to_end() -> None:
    # Injecting ``compact_digest`` at the top level reaches the sub-researcher's
    # reflect prompt (opt-in), swapping it to the note-compacted notebook.
    capture = _PipelineCapture(
        plan=plan_payload([_SUBQ]), action={"query": "go", "enough": False}, finding=_FINDING
    )
    await _run_pipeline(capture, digest_fn=compact_digest)
    assert capture.reflect_prompts[1] == _reflect_prompt(compact_digest(_RESULTS))
    assert capture.reflect_prompts[1] != _reflect_prompt(_results_digest(_RESULTS))
