"""Lead/orchestrator agent for the Deep Research lane (Spec 009 Req 3).

The lead agent does what the Anthropic multi-agent research system calls the
"lead": it turns a raw query into a scoped ``ResearchBrief`` and decomposes it
into a ``ResearchPlan`` of self-contained, non-overlapping ``SubQuestion``s — the
LLM, not the code, decides the breakdown (the orchestrator-workers planner
idiom). The brief's ``out_of_scope`` list is the explicit-exclusion seam that
keeps the parallel sub-researchers from drifting onto each other's ground.

An optional ``clarify`` pre-step sharpens an ambiguous query before planning (the
scoping phase open_deep_research runs first); it is off by default so offline
runs stay single-call and deterministic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from patterns_contracts import ResearchPlan
from pydantic_ai import Agent
from pydantic_ai.models.instrumented import instrument_model

if TYPE_CHECKING:
    from pydantic_ai.models import Model
    from pydantic_ai.models.instrumented import InstrumentationSettings

__all__ = ["build_brief_and_plan"]


_CLARIFIER_INSTRUCTIONS = (
    "You sharpen a research query before it is planned. Restate the user's query "
    "as a single, specific, self-contained research question, resolving obvious "
    "ambiguity without inventing facts. Return only the sharpened question."
)

_PLANNER_INSTRUCTIONS = (
    "You are the lead agent of a research team. First write a ResearchBrief: the "
    "objective a complete answer must satisfy, and an out_of_scope list of explicit "
    "exclusions. Then decompose the work into a small list of self-contained "
    "subquestions (typically 2-4). Each subquestion must be answerable on its own, "
    "without seeing the others, and must not overlap another subquestion's ground."
)


async def build_brief_and_plan(
    query: str,
    *,
    model: Model,
    clarify: bool = False,
    instrumentation: InstrumentationSettings | None = None,
) -> ResearchPlan:
    """Scope ``query`` into a brief and decompose it into a research plan.

    Args:
        query: The raw user research query.
        model: PydanticAI model powering the lead agent (DI seam shared with the
            other stages). Tests inject a scripted ``FunctionModel``; the
            integration lane injects an Ollama-backed model.
        clarify: When ``True``, a clarifier pre-step sharpens the query before
            planning. Off by default to keep offline runs single-call.
        instrumentation: Optional ``InstrumentationSettings``; when set the model
            is wrapped via ``instrument_model`` so ``gen_ai.*`` spans flow. ``None``
            keeps the run uninstrumented.

    Returns:
        A :class:`~patterns_contracts.ResearchPlan` whose ``brief`` carries the
        objective/out-of-scope and whose ``subquestions`` are the planner's full,
        uncapped decomposition (the fan-out cap is applied downstream).
    """
    resolved = instrument_model(model, instrumentation) if instrumentation else model

    scoped = query
    if clarify:
        clarifier = Agent[None, str](
            model=resolved,
            output_type=str,
            instructions=_CLARIFIER_INSTRUCTIONS,
            deps_type=type(None),
        )
        scoped = (await clarifier.run(query)).output

    planner = Agent[None, ResearchPlan](
        model=resolved,
        output_type=ResearchPlan,
        instructions=_PLANNER_INSTRUCTIONS,
        deps_type=type(None),
    )
    return (await planner.run(f"Research query: {scoped}")).output
