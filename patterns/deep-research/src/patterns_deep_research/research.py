"""Top-level Deep Research orchestration (Spec 009 Req 4.1, 7, 10).

``run_deep_research`` is the lane's single public entry. It composes the existing
agent primitives into the Anthropic orchestrator/sub-researcher architecture:

1. the **lead** agent scopes the query into a brief and plan
   (:mod:`patterns_deep_research.orchestrator`);
2. the plan is **capped** at ``max_researchers`` (``ResearchReport.truncated``
   records any cut) — the orchestrator-workers fan-out guard, so an unbounded plan
   never becomes unbounded LLM calls (OWASP excessive-agency / unbounded-consumption);
3. the capped subquestions fan out in parallel via ``asyncio.gather`` (plan order
   preserved), each a bounded sub-researcher
   (:mod:`patterns_deep_research.researcher`);
4. the report writer synthesises a citation-grounded report
   (:mod:`patterns_deep_research.report`).

Progress is reported through an optional ``on_event`` callback seam carrying the
``ProgressEvent`` discriminated union; a consumer (e.g. the SSE lane) adapts those
to its own wire vocabulary outside this lane, so the lane src imports no sibling
(NFR-3). The multi-agent fan-out is the ~15x-token cost the caps exist to bound.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from patterns_contracts import (
    BriefReadyEvent,
    FindingReadyEvent,
    PlanReadyEvent,
    ReportReadyEvent,
    ResearcherStartedEvent,
)
from pydantic_ai.models.instrumented import instrument_model

from patterns_deep_research.orchestrator import build_brief_and_plan
from patterns_deep_research.report import write_report
from patterns_deep_research.researcher import run_subquestion

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from patterns_contracts import (
        Finding,
        ProgressEvent,
        ResearchReport,
        SearchResult,
        SubQuestion,
    )
    from pydantic_ai.models import Model
    from pydantic_ai.models.instrumented import InstrumentationSettings

    from patterns_deep_research.search import SearchProvider

__all__ = ["run_deep_research"]


async def run_deep_research(
    query: str,
    *,
    model: Model,
    search: SearchProvider,
    max_researchers: int = 3,
    max_iterations: int = 3,
    top_k: int = 5,
    clarify: bool = False,
    instrumentation: InstrumentationSettings | None = None,
    on_event: Callable[[ProgressEvent], Awaitable[None]] | None = None,
    digest_fn: Callable[[Sequence[SearchResult]], str] | None = None,
) -> ResearchReport:
    """Run the full Deep Research pipeline for ``query`` (Req 4.1).

    Args:
        query: The user research query.
        model: PydanticAI model powering every stage (DI seam). Tests inject scripted
            ``FunctionModel``s; the integration lane injects an Ollama-backed model.
        search: The injected ``SearchProvider`` the sub-researchers gather from — the
            only door to the outside world (least privilege, Req 7).
        max_researchers: Fan-out cap on parallel sub-researchers; plan subquestions
            beyond it are dropped and flagged via ``ResearchReport.truncated`` (Req 7).
            Must be >= 1.
        max_iterations: Per-researcher search→read→reflect cap (Req 4.3). Must be >= 1.
        top_k: Per-search result cap (Req 7). Must be >= 1.
        clarify: When ``True``, the lead clarifies the query before planning.
        instrumentation: Optional ``InstrumentationSettings``; when set every model
            call across the run emits ``gen_ai.*`` spans into its provider. Applied
            once here and shared down the stages (no double-wrapping). ``None`` runs
            uninstrumented.
        on_event: Optional async progress callback receiving the ``ProgressEvent``
            union (brief → plan → researcher_started* → finding_ready* → report_ready).
        digest_fn: Optional reflect-loop digest seam threaded to every sub-researcher
            (Spec 010 Req 1.1-1.2). ``None`` (default) leaves each researcher on its own
            ``_results_digest`` default — byte-compatible current behaviour; inject
            ``notes.compact_digest`` to opt the whole run into note-based compaction.

    Returns:
        A :class:`~patterns_contracts.ResearchReport` whose ``findings`` hold at most
        ``max_researchers`` entries in plan order, whose ``citations`` are the
        deduplicated union, and whose ``truncated`` discloses any fan-out cut.

    Raises:
        ValueError: If any cap (``max_researchers`` / ``max_iterations`` / ``top_k``)
            is not positive — a zero/negative cap would silently empty the run.
        EmptyCitationError | DanglingCitationError: When a sub-researcher's finding
            cites nothing or an unretrieved source (raised in the researcher).
    """
    if max_researchers < 1:
        msg = f"max_researchers must be >= 1, got {max_researchers}"
        raise ValueError(msg)
    if max_iterations < 1:
        msg = f"max_iterations must be >= 1, got {max_iterations}"
        raise ValueError(msg)
    if top_k < 1:
        msg = f"top_k must be >= 1, got {top_k}"
        raise ValueError(msg)

    # Instrument once and share the resolved model down the stages; the stages are
    # called with instrumentation=None so they never re-wrap an already-wrapped model.
    resolved = instrument_model(model, instrumentation) if instrumentation else model

    async def _emit(event: ProgressEvent) -> None:
        if on_event is not None:
            await on_event(event)

    plan = await build_brief_and_plan(query, model=resolved, clarify=clarify)
    await _emit(BriefReadyEvent(objective=plan.brief.objective))

    selected = plan.subquestions[:max_researchers]
    truncated = len(plan.subquestions) > max_researchers
    await _emit(PlanReadyEvent(count=len(selected)))

    async def _research(subquestion: SubQuestion) -> Finding:
        await _emit(ResearcherStartedEvent(subquestion=subquestion.description))
        # Forward the seam only when injected so an un-opted run keeps the
        # researcher's own ``_results_digest`` default (research.py never imports
        # that private symbol; the researcher owns its reflect-digest default).
        if digest_fn is None:
            finding = await run_subquestion(
                subquestion,
                model=resolved,
                search=search,
                max_iterations=max_iterations,
                top_k=top_k,
            )
        else:
            finding = await run_subquestion(
                subquestion,
                model=resolved,
                search=search,
                max_iterations=max_iterations,
                top_k=top_k,
                digest_fn=digest_fn,
            )
        await _emit(
            FindingReadyEvent(
                subquestion=subquestion.description,
                citation_count=len(finding.citations),
            )
        )
        return finding

    # gather preserves input order, so findings line up with the plan (Req 4.1).
    findings = list(await asyncio.gather(*(_research(sq) for sq in selected)))

    report = await write_report(plan.brief, findings, model=resolved, truncated=truncated)
    await _emit(ReportReadyEvent(citation_count=len(report.citations)))
    return report
