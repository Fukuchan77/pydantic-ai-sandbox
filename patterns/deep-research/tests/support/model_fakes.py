"""Scripted ``FunctionModel`` fakes for deterministic Deep Research tests.

``TestModel`` (used by the smoke test) generates schema-valid but arbitrary data;
the pipeline tests instead need *chosen* plans, reflect decisions, finding drafts,
and report text. ``scripted_model`` dispatches on the output tool's property names
so a single fake serves every stage of the pipeline and stays correct under the
parallel ``asyncio.gather`` fan-out (it is stateless — no call cursor to interleave):

* ``subquestions`` in the schema  → a ``ResearchPlan`` payload (the lead agent);
* ``enough`` in the schema        → a ``_ResearchAction`` payload (reflect step);
* ``cited_sources`` in the schema → a ``_FindingDraft`` payload (compression);
* no output tool (plain ``str``)  → the clarifier / report writer text.

A fixed per-call token usage is surfaced so an instrumented run produces spans
deterministically.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from patterns_contracts import AxisScore, GradeReport
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage

if TYPE_CHECKING:
    from collections.abc import Sequence

    from patterns_contracts import Rating, ResearchNote, ResearchReport
    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.models.function import AgentInfo

__all__ = [
    "FakeResearchReportJudge",
    "faithfulness_rating_for",
    "plan_payload",
    "scripted_model",
]

_DEFAULT_ACTION: dict[str, Any] = {"query": "deep research multi-agent", "enough": True}
_DEFAULT_FINDING: dict[str, Any] = {
    "summary": "Multi-agent research uses a lead plus parallel sub-researchers.",
    "cited_sources": ["anthropic-multi-agent"],
}


def plan_payload(
    subquestions: Sequence[str],
    *,
    query: str = "the research query",
    objective: str = "Cover the trade-offs of multi-agent research systems.",
    out_of_scope: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Build a ``ResearchPlan``-shaped payload from a list of subquestion strings."""
    return {
        "brief": {
            "query": query,
            "objective": objective,
            "out_of_scope": list(out_of_scope or []),
        },
        "subquestions": [{"description": description} for description in subquestions],
    }


def scripted_model(
    *,
    plan: dict[str, Any] | None = None,
    action: dict[str, Any] | None = None,
    finding: dict[str, Any] | None = None,
    text: str = "A synthesised research report grounded in the findings.",
    tokens: int = 7,
    model_name: str = "fake-deep-research",
) -> FunctionModel:
    """Build a ``FunctionModel`` returning canned per-stage responses by output schema.

    Args:
        plan: Args for the ``ResearchPlan`` output tool (schema exposes ``subquestions``).
        action: Args for the ``_ResearchAction`` tool (schema exposes ``enough``);
            defaults to ``{"query": ..., "enough": True}`` so a researcher runs once.
        finding: Args for the ``_FindingDraft`` tool (schema exposes ``cited_sources``);
            defaults to a single grounded citation.
        text: Response for plain-text (``output_type=str``) requests (clarifier / report).
        tokens: Output-token usage surfaced on each response so an instrumented run
            produces spans deterministically.
        model_name: Identifier surfaced in instrumentation spans.

    Returns:
        A ``FunctionModel`` usable anywhere the pipeline accepts ``model``.

    Raises:
        AssertionError: At call time, when an output schema is requested that the
            script has no payload for — a test-authoring error that fails loudly.
    """
    action_payload = action if action is not None else _DEFAULT_ACTION
    finding_payload = finding if finding is not None else _DEFAULT_FINDING

    def _respond(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        usage = RequestUsage(output_tokens=tokens)
        if info.output_tools:
            tool = info.output_tools[0]
            properties: dict[str, Any] = tool.parameters_json_schema.get("properties", {})
            if "subquestions" in properties:
                if plan is None:
                    msg = "scripted_model: a ResearchPlan was requested but no plan payload was set"
                    raise AssertionError(msg)
                return ModelResponse(parts=[ToolCallPart(tool.name, plan)], usage=usage)
            if "enough" in properties:
                return ModelResponse(parts=[ToolCallPart(tool.name, action_payload)], usage=usage)
            if "cited_sources" in properties:
                return ModelResponse(parts=[ToolCallPart(tool.name, finding_payload)], usage=usage)
            msg = f"scripted_model has no payload for output schema: {sorted(properties)}"
            raise AssertionError(msg)
        return ModelResponse(parts=[TextPart(text)], usage=usage)

    return FunctionModel(_respond, model_name=model_name)


def faithfulness_rating_for(notes: Sequence[ResearchNote]) -> Rating:
    """Map distilled-note signal to a faithfulness ``Rating`` (Spec 011 Req 2.4).

    Evidence-deficient input maps to ``"unknown"`` -- never a silent numeric
    score: an empty notebook, or notes whose ``key_point`` is empty/whitespace
    only (the distiller emits an empty key point from a blank snippet), carry no
    signal to ground faithfulness on. Otherwise the rating scales with the share
    of notes that survived distillation with a non-blank key point (full signal
    -> ``"5"``, partial -> ``"3"``); the numeric scale is illustrative while the
    Unknown discipline is the tested contract.

    Args:
        notes: The distilled ``ResearchNote``s gathered for the graded subject.

    Returns:
        ``"unknown"`` when no note carries a non-blank key point, else a discrete
        numeric rating reflecting the grounded share.
    """
    grounded = sum(1 for note in notes if note.key_point.strip())
    if grounded == 0:
        return "unknown"
    return "5" if grounded == len(notes) else "3"


class FakeResearchReportJudge:
    """Deterministic independent ``Judge[ResearchReport]`` for hermetic lane evals.

    Scores a ``ResearchReport`` into the shared ``GradeReport`` with no network
    I/O (Spec 011 Req 3.2/4.1). Outcome axes are scripted; the behavior
    faithfulness axis is derived from the report's distilled ``Finding.notes``
    via :func:`faithfulness_rating_for`, so the Req 2.4 Unknown-mapping
    discipline runs through the very helper the test pins directly rather than a
    verdict baked into this fake (no tautology). ``judge_id`` records provenance
    so a graded report is attributable to an independent grader (Req 3.3).
    """

    def __init__(self, *, judge_id: str = "fake-research-judge") -> None:
        """Store the provenance id stamped onto every produced ``GradeReport``."""
        self._judge_id = judge_id

    async def grade(self, subject: ResearchReport, /) -> GradeReport:
        """Grade ``subject`` into an outcome+behavior ``GradeReport`` (helper-driven faithfulness)."""
        notes = [note for finding in subject.findings for note in finding.notes]
        grounded = sum(1 for note in notes if note.key_point.strip())
        return GradeReport(
            outcome_scores=[
                AxisScore(
                    criterion="completeness",
                    rating="4",
                    rationale=f"{len(subject.findings)} finding(s) address the brief objective.",
                ),
            ],
            behavior_scores=[
                AxisScore(
                    criterion="faithfulness",
                    rating=faithfulness_rating_for(notes),
                    rationale=(
                        f"{grounded}/{len(notes)} distilled notes carry a grounded key point"
                        if notes
                        else "no distilled notes gathered; faithfulness is evidence-deficient"
                    ),
                ),
            ],
            aggregate=round(grounded / len(notes), 2) if notes else 0.0,
            judge_id=self._judge_id,
        )
