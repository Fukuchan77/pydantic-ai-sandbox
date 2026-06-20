"""Deep Research multi-agent application lane of the cross-framework patterns.

This package implements the Anthropic orchestrator/sub-researcher architecture on
PydanticAI primitives (Spec 009): a lead agent scopes a query into a brief/plan,
bounded parallel sub-researchers run search→read→reflect loops over an injected
``SearchProvider``, and a report writer synthesises a citation-grounded report.
The public surface is flattened here so callers import the entry, the search seam,
and the loud-fail exceptions from one place:

* ``run_deep_research`` — the only public orchestration entry;
* ``SearchProvider`` / ``load_search_provider`` — the search DI seam and its live loader;
* the shared contract types (``ResearchReport`` / ``Finding`` / … / ``ProgressEvent``),
  re-exported from ``patterns_contracts`` so the lane has a single import surface;
* the citation-soundness exceptions ``CitationError`` / ``EmptyCitationError`` /
  ``DanglingCitationError`` that the pipeline raises on ungrounded findings.

``configure_tracing`` is intentionally *not* re-exported: by the lane's boundary
discipline it is imported directly from :mod:`patterns_deep_research.observability`.
"""

from __future__ import annotations

from patterns_contracts import (
    BriefReadyEvent,
    Citation,
    Finding,
    FindingReadyEvent,
    PlanReadyEvent,
    ProgressEvent,
    ReportReadyEvent,
    ResearchBrief,
    ResearcherStartedEvent,
    ResearchPlan,
    ResearchReport,
    SearchQuery,
    SearchResult,
    SubQuestion,
)

from patterns_deep_research.compression import (
    CitationError,
    DanglingCitationError,
    EmptyCitationError,
)
from patterns_deep_research.research import run_deep_research
from patterns_deep_research.search import SearchProvider, load_search_provider

__all__ = [
    "BriefReadyEvent",
    "Citation",
    "CitationError",
    "DanglingCitationError",
    "EmptyCitationError",
    "Finding",
    "FindingReadyEvent",
    "PlanReadyEvent",
    "ProgressEvent",
    "ReportReadyEvent",
    "ResearchBrief",
    "ResearchPlan",
    "ResearchReport",
    "ResearcherStartedEvent",
    "SearchProvider",
    "SearchQuery",
    "SearchResult",
    "SubQuestion",
    "load_search_provider",
    "run_deep_research",
]
