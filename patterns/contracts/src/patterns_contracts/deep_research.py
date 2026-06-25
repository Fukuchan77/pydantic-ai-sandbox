"""Deep Research application-layer contracts (Spec 009-deep-research Req 2.1).

This module is the single source of truth for the Deep Research pattern's
brief / plan / finding / report Pydantic models and the ``ProgressEvent``
discriminated union; the normative copy also lives in
``patterns/deep-research/README.md`` fenced block, asserted equal by the
single-point drift test (Spec 006-2a NFR-5). The Deep Research lane
(``patterns_deep_research``) imports these via the ``patterns/contracts`` path
dependency rather than duplicating them (NFR-3).

Deep Research is an *application layer* (not one of the six workflow patterns):
an orchestrator/lead agent decomposes a query into a ``ResearchBrief`` +
``ResearchPlan`` of self-contained ``SubQuestion``s, bounded parallel
sub-researchers each run a search→read→reflect loop and return a ``Finding``,
and a report writer synthesises a ``ResearchReport`` (Anthropic multi-agent
research system / langchain open_deep_research / local-deep-research).

``Citation`` is **reused** from :mod:`patterns_contracts.rag` (not redefined
here): a research claim is grounded exactly like a RAG answer's claim — a source
anchor that must point at a result the researcher actually saw. The drift test
enforces one-class-one-README ownership, so ``Citation`` stays documented in the
RAG README and is only *referenced* in the Deep Research README, never re-declared.

The grounding invariants (≥1 citation per ``Finding``, no dangling citation) and
the cap-enforcement flags (``truncated``) are enforced in the lane pipeline
(``patterns_deep_research.compression`` / ``.research``), not as field
constraints here — the contract stays a plain, dependency-zero shape.

The ``ProgressEvent`` ``Annotated`` union is skipped symmetrically by the drift
parser (it is neither a model class nor a ``Literal``), matching the ``SseEvent``
precedent; each member's ``type`` ``Literal`` doubles as a progress-event name a
consumer (e.g. the SSE lane) can map onto its own wire vocabulary.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

# Runtime import (not TYPE_CHECKING): pydantic resolves ``list[Citation]`` when it
# builds the model schema, so the real type must be importable at class-definition
# time even under ``from __future__ import annotations``.
from patterns_contracts.rag import Citation  # noqa: TC001  # reused, not redefined

__all__ = [
    "BriefReadyEvent",
    "Finding",
    "FindingReadyEvent",
    "PlanReadyEvent",
    "ProgressEvent",
    "ReportReadyEvent",
    "ResearchBrief",
    "ResearchNote",
    "ResearchPlan",
    "ResearchReport",
    "ResearcherStartedEvent",
    "SearchQuery",
    "SearchResult",
    "SubQuestion",
]


class ResearchBrief(BaseModel):
    """The lead agent's scoped restatement of the user query (Anthropic lead-agent brief)."""

    query: str = Field(description="The original user query, verbatim.")
    objective: str = Field(description="What a complete answer must cover (the success criteria).")
    out_of_scope: list[str] = Field(
        description="Explicit exclusions that keep sub-researchers from drifting off-task."
    )


class SubQuestion(BaseModel):
    """One focused, self-contained research task for a single sub-researcher."""

    description: str = Field(
        description="Self-contained instruction answerable without seeing the other subquestions."
    )


class ResearchPlan(BaseModel):
    """The lead agent's decomposition of the brief into ordered subquestions."""

    brief: ResearchBrief = Field(description="The scoped brief the plan addresses.")
    subquestions: list[SubQuestion] = Field(
        description="Ordered subquestions; capped at max_researchers downstream (fan-out guard)."
    )


class SearchQuery(BaseModel):
    """A query a sub-researcher issues to the injected ``SearchProvider`` seam."""

    text: str = Field(description="The search query text the researcher decided to run.")


class SearchResult(BaseModel):
    """One hit returned by the ``SearchProvider`` seam, grounding a finding."""

    source: str = Field(
        description="Document identifier the hit came from (feeds Citation.source)."
    )
    locator: str = Field(
        description="Anchor within the source (e.g. url / section); feeds Citation.locator."
    )
    snippet: str = Field(description="The result text used to ground a finding.")
    score: float = Field(description="Provider relevance score; ties break by ascending source.")


class ResearchNote(BaseModel):
    """One distilled, high-signal note kept in a sub-researcher's external notebook.

    Structured note-taking carrier (Anthropic "Effective context engineering"):
    each gathered ``SearchResult`` is reduced to a single ``key_point`` and kept
    as external memory rather than raw transcript, deduplicated by its
    ``(source, locator)`` anchor and ranked by ``score`` (lane-side compaction in
    ``patterns_deep_research.notes``). ``frozen=True`` keeps a note immutable and
    hashable once distilled. The v1 shape is fixed at these four fields; an
    adoption/rejection ``decision`` family ("information that constrains future
    reasoning") is a documented future extension, not part of this contract.
    """

    model_config = {"frozen": True}

    source: str = Field(description="Distilled-from SearchResult.source; dedup anchor.")
    locator: str = Field(description="Distilled-from SearchResult.locator; dedup anchor.")
    key_point: str = Field(
        description="Lead sentence truncated to key_point_chars with a visible marker."
    )
    score: float = Field(description="Distilled-from SearchResult.score; descending-rank key.")


class Finding(BaseModel):
    """One sub-researcher's compressed output for its subquestion."""

    subquestion: SubQuestion = Field(description="The subquestion this finding answers.")
    summary: str = Field(description="Compressed findings for the subquestion.")
    citations: list[Citation] = Field(
        description="Sources backing the summary (>=1 enforced by the pipeline)."
    )
    iterations: int = Field(
        description="search→read→reflect loops actually run (<= max_iterations)."
    )
    truncated: bool = Field(
        default=False,
        description="True when the per-researcher iteration cap was hit before 'enough'.",
    )
    notes: list[ResearchNote] = Field(
        default=[],
        description="Distilled high-signal notes for the handoff (default []; raw transcript not propagated).",
    )


class ResearchReport(BaseModel):
    """The final synthesised Deep Research output.

    ``findings`` holds at most ``max_researchers`` entries in plan order; together
    with ``truncated`` this makes fan-out cap enforcement discernible from the
    result alone (the orchestrator-workers ``OrchestratedResult.truncated`` idiom).
    """

    brief: ResearchBrief = Field(description="The brief the report addresses.")
    findings: list[Finding] = Field(description="Per-subquestion findings, in plan order.")
    report: str = Field(description="The synthesised report text with inline citation markers.")
    citations: list[Citation] = Field(
        description="Deduplicated union of every finding's citations."
    )
    truncated: bool = Field(
        default=False,
        description="True when the plan emitted more subquestions than max_researchers allowed.",
    )


class BriefReadyEvent(BaseModel):
    """Progress: the lead agent produced the research brief."""

    type: Literal["brief_ready"] = "brief_ready"
    objective: str = Field(description="The brief's objective (the success criteria).")


class PlanReadyEvent(BaseModel):
    """Progress: the lead agent produced the (capped) research plan."""

    type: Literal["plan_ready"] = "plan_ready"
    count: int = Field(description="Number of subquestions that will run (after the fan-out cap).")


class ResearcherStartedEvent(BaseModel):
    """Progress: a sub-researcher began work on its subquestion."""

    type: Literal["researcher_started"] = "researcher_started"
    subquestion: str = Field(description="The subquestion description the researcher started.")


class FindingReadyEvent(BaseModel):
    """Progress: a sub-researcher returned a grounded finding."""

    type: Literal["finding_ready"] = "finding_ready"
    subquestion: str = Field(description="The subquestion the finding answers.")
    citation_count: int = Field(description="Number of citations backing the finding.")


class ReportReadyEvent(BaseModel):
    """Progress: the report writer produced the final report (terminal event)."""

    type: Literal["report_ready"] = "report_ready"
    citation_count: int = Field(description="Number of deduplicated citations in the report.")


ProgressEvent = Annotated[
    BriefReadyEvent
    | PlanReadyEvent
    | ResearcherStartedEvent
    | FindingReadyEvent
    | ReportReadyEvent,
    Field(discriminator="type"),
]
"""Discriminated union of Deep Research progress events, tagged by ``type``.

Emitted through the lane's optional ``on_event`` seam so a consumer can stream
research progress. Like ``SseEvent`` this is an ``Annotated`` alias — neither a
model class nor a ``Literal`` — so the drift parser skips it symmetrically on
both the README and package sides. ``TypeAdapter(ProgressEvent).validate_json``
reverses a dumped payload back to the matching member."""
