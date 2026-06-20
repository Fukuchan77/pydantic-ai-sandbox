"""Report writer for the Deep Research lane (Spec 009 Req 6).

The final stage merges the parallel sub-researchers' findings into one coherent,
citation-grounded report — the synthesizer role of the orchestrator-workers
pattern, applied to research. The synthesizer writes prose; this module owns the
deterministic assembly around it: the report's citation list is the deduplicated
union of every finding's citations (so an anchor cited twice appears once), and
the fan-out ``truncated`` flag is propagated from the caller so the final result
discloses whether the plan was capped.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from patterns_contracts import ResearchReport
from pydantic_ai import Agent
from pydantic_ai.models.instrumented import instrument_model

from patterns_deep_research.compression import dedup_citations

if TYPE_CHECKING:
    from collections.abc import Sequence

    from patterns_contracts import Finding, ResearchBrief
    from pydantic_ai.models import Model
    from pydantic_ai.models.instrumented import InstrumentationSettings

__all__ = ["write_report"]


_SYNTHESIZER_INSTRUCTIONS = (
    "You are a report writer. Merge the research findings you are given into one "
    "coherent report that answers the brief's objective. Ground every claim in the "
    "findings, reference sources inline, and do not introduce facts absent from them."
)


def _findings_digest(findings: Sequence[Finding]) -> str:
    """Render findings as a stable prompt block (subquestion + summary + sources)."""
    blocks: list[str] = []
    for finding in findings:
        sources = ", ".join(citation.source for citation in finding.citations)
        blocks.append(
            f"Subquestion: {finding.subquestion.description}\n"
            f"Summary: {finding.summary}\n"
            f"Sources: {sources}"
        )
    return "\n\n".join(blocks)


async def write_report(
    brief: ResearchBrief,
    findings: Sequence[Finding],
    *,
    model: Model,
    truncated: bool = False,
    instrumentation: InstrumentationSettings | None = None,
) -> ResearchReport:
    """Synthesise the findings into a citation-grounded ``ResearchReport`` (Req 6).

    Args:
        brief: The scoped brief the report must address.
        findings: The per-subquestion findings, in plan order.
        model: PydanticAI model powering the synthesizer (DI seam).
        truncated: Propagated fan-out flag — ``True`` when the plan was capped at
            ``max_researchers`` upstream.
        instrumentation: Optional ``InstrumentationSettings``; when set the
            synthesizer call emits ``gen_ai.*`` spans. ``None`` runs uninstrumented.

    Returns:
        A :class:`~patterns_contracts.ResearchReport` whose ``citations`` are the
        deduplicated union of the findings' citations and whose ``truncated`` mirrors
        the caller's fan-out cap state.
    """
    resolved = instrument_model(model, instrumentation) if instrumentation else model
    synthesizer = Agent[None, str](
        model=resolved,
        output_type=str,
        instructions=_SYNTHESIZER_INSTRUCTIONS,
        deps_type=type(None),
    )
    report_text = (
        await synthesizer.run(
            f"Objective: {brief.objective}\n\nFindings:\n{_findings_digest(findings)}"
        )
    ).output

    citations = dedup_citations([c for finding in findings for c in finding.citations])
    return ResearchReport(
        brief=brief,
        findings=list(findings),
        report=report_text,
        citations=citations,
        truncated=truncated,
    )
