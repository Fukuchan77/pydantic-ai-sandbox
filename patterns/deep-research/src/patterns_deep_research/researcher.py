"""Sub-researcher agent for the Deep Research lane (Spec 009 Req 4).

One sub-researcher owns one ``SubQuestion`` in its own context window (the
Anthropic separate-context principle that stops parallel researchers from
colliding). It runs a **bounded** search→read→reflect loop — the autonomous-agent
guardrail discipline re-cast for research: at most ``max_iterations`` model turns,
each search bounded to ``top_k`` results, the injected ``SearchProvider`` the only
tool it can reach (least privilege). When the loop hits the cap before the agent
judges the evidence sufficient, ``Finding.truncated`` records it — cap enforcement
stays visible from the result alone (the orchestrator-workers ``truncated`` idiom).

A final compression turn writes the finding summary and chooses which retrieved
sources to cite; :mod:`patterns_deep_research.compression` grounds those choices
into ``Citation``s and loud-fails on an empty or dangling citation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from patterns_contracts import Finding, SearchQuery
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.instrumented import instrument_model

from patterns_deep_research.compression import map_citations

if TYPE_CHECKING:
    from patterns_contracts import SearchResult, SubQuestion
    from pydantic_ai.models import Model
    from pydantic_ai.models.instrumented import InstrumentationSettings

    from patterns_deep_research.search import SearchProvider

__all__ = ["run_subquestion"]


_ACTION_INSTRUCTIONS = (
    "You research one subquestion by searching iteratively. Given the subquestion "
    "and the results gathered so far, return the next search query to run (an "
    "empty query if no further search is needed) and whether the gathered results "
    "are now enough to answer the subquestion. Stop as soon as the evidence suffices."
)

_COMPRESS_INSTRUCTIONS = (
    "You compress research results into a finding. Given the subquestion and the "
    "gathered results, write a concise summary grounded only in those results, and "
    "list the source identifiers you actually used. Cite only sources present in "
    "the gathered results; never invent a source."
)


class _ResearchAction(BaseModel):
    """The reflect step's decision: the next query and whether to stop."""

    query: str = Field(description="Next search query to run; empty when no more search is needed.")
    enough: bool = Field(description="True when the gathered results suffice to answer.")


class _FindingDraft(BaseModel):
    """The compression step's draft: a grounded summary and the sources it used."""

    summary: str = Field(description="Concise summary grounded only in the gathered results.")
    cited_sources: list[str] = Field(description="Source identifiers actually used (>=1).")


def _results_digest(results: list[SearchResult]) -> str:
    """Render gathered results as a stable prompt block (source/locator/snippet)."""
    if not results:
        return "(no results gathered yet)"
    return "\n".join(
        f"- source={result.source} locator={result.locator}: {result.snippet}" for result in results
    )


async def run_subquestion(
    subquestion: SubQuestion,
    *,
    model: Model,
    search: SearchProvider,
    max_iterations: int = 3,
    top_k: int = 5,
    instrumentation: InstrumentationSettings | None = None,
) -> Finding:
    """Run the bounded search→read→reflect loop for one subquestion (Req 4.2-4.4).

    Args:
        subquestion: The self-contained subquestion to research.
        model: PydanticAI model powering the reflect and compression turns (DI seam).
        search: The injected ``SearchProvider`` — the only tool the researcher can
            reach (least privilege, Req 7).
        max_iterations: Hard cap on reflect turns; on exhaustion the finding is
            flagged ``truncated`` (Req 4.3). Must be >= 1.
        top_k: Per-search result cap (unbounded-consumption guard, Req 7). Must be >= 1.
        instrumentation: Optional ``InstrumentationSettings``; when set every model
            call emits ``gen_ai.*`` spans. ``None`` runs uninstrumented.

    Returns:
        A :class:`~patterns_contracts.Finding` with the grounded summary, the
        citations mapped from the sources actually retrieved, the number of
        iterations run, and the ``truncated`` flag.

    Raises:
        ValueError: If ``max_iterations`` or ``top_k`` is not positive — either
            would make the loop meaningless rather than fail loudly.
        EmptyCitationError | DanglingCitationError: When the compression step cites
            nothing or a source no search returned (raised by ``map_citations``).
    """
    if max_iterations < 1:
        msg = f"max_iterations must be >= 1, got {max_iterations}"
        raise ValueError(msg)
    if top_k < 1:
        msg = f"top_k must be >= 1, got {top_k}"
        raise ValueError(msg)

    resolved = instrument_model(model, instrumentation) if instrumentation else model
    action_agent = Agent[None, _ResearchAction](
        model=resolved,
        output_type=_ResearchAction,
        instructions=_ACTION_INSTRUCTIONS,
        deps_type=type(None),
    )

    collected: list[SearchResult] = []
    iterations = 0
    truncated = True  # flipped to False the moment the agent judges the evidence enough
    for index in range(max_iterations):
        iterations = index + 1
        action = (
            await action_agent.run(
                f"Subquestion: {subquestion.description}\n\n"
                f"Results so far:\n{_results_digest(collected)}"
            )
        ).output
        if action.query.strip():
            collected.extend(await search.search(SearchQuery(text=action.query), top_k=top_k))
        if action.enough:
            truncated = False
            break

    compress_agent = Agent[None, _FindingDraft](
        model=resolved,
        output_type=_FindingDraft,
        instructions=_COMPRESS_INSTRUCTIONS,
        deps_type=type(None),
    )
    draft = (
        await compress_agent.run(
            f"Subquestion: {subquestion.description}\n\n"
            f"Gathered results:\n{_results_digest(collected)}"
        )
    ).output

    citations = map_citations(draft.cited_sources, collected)
    return Finding(
        subquestion=subquestion,
        summary=draft.summary,
        citations=citations,
        iterations=iterations,
        truncated=truncated,
    )
