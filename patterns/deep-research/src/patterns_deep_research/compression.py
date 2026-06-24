"""Citation grounding and compression for the Deep Research lane (Spec 009 Req 5).

A finding is only trustworthy if every source it cites is one the researcher
actually retrieved. This module is the contract-level defence against the two
ways grounding breaks — porting the RAG lane's citation-soundness discipline to
research findings: a finding that cites nothing (``EmptyCitationError``) and a
finding citing a source no search returned — a *dangling* citation, the
citation-spoofing failure mode (``DanglingCitationError``). Both loud-fail rather
than passing a fabricated source downstream as if it were grounded.

``Citation`` is reused from the RAG contract; the deterministic soundness key is
``chunk_id = f"{source}::{locator}"`` over the ``SearchResult`` the citation is
built from, so a citation is grounded iff its source was retrieved.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from patterns_contracts import Citation

if TYPE_CHECKING:
    from collections.abc import Sequence

    from patterns_contracts import SearchResult

__all__ = [
    "CitationError",
    "DanglingCitationError",
    "EmptyCitationError",
    "dedup_citations",
    "map_citations",
]


class CitationError(Exception):
    """Base class for citation-soundness violations that loud-fail a finding."""


class EmptyCitationError(CitationError):
    """Raised when a finding cites no source at all (Req 5.2)."""


class DanglingCitationError(CitationError):
    """Raised when a cited source matches no retrieved result (Req 5.3, spoofing guard)."""


def _chunk_id(result: SearchResult) -> str:
    """Deterministic soundness key for a result (mirrors the RAG chunk_id anchor)."""
    return f"{result.source}::{result.locator}"


def map_citations(
    cited_sources: Sequence[str],
    retrieved: Sequence[SearchResult],
) -> list[Citation]:
    """Map a researcher's chosen sources to grounded ``Citation``s.

    Args:
        cited_sources: Source identifiers the compression step chose to cite.
        retrieved: The results the researcher actually saw, that ground the finding.

    Returns:
        One :class:`~patterns_contracts.Citation` per distinct cited source, in the
        order first cited, each anchored to the highest-scoring retrieved result for
        that source (ties break by ascending locator — deterministic).

    Raises:
        EmptyCitationError: When ``cited_sources`` is empty (Req 5.2). Checked
            first, so a finding that cited nothing fails as empty, not dangling.
        DanglingCitationError: When any cited source is absent from ``retrieved``
            (Req 5.3); the message names every dangling source and the known set.
    """
    if not cited_sources:
        raise EmptyCitationError("A finding must cite at least one source, got none.")

    known = {result.source for result in retrieved}
    dangling = sorted({source for source in cited_sources if source not in known})
    if dangling:
        raise DanglingCitationError(
            f"Cited source(s) {dangling} not in retrieved set {sorted(known)}."
        )

    citations: list[Citation] = []
    seen: set[str] = set()
    for source in cited_sources:
        if source in seen:
            continue
        seen.add(source)
        # Highest score wins; ascending locator breaks ties so the anchor is stable.
        best = max(
            (result for result in retrieved if result.source == source),
            key=lambda result: (result.score, _negated_locator(result.locator)),
        )
        citations.append(
            Citation(
                source=best.source,
                locator=best.locator,
                chunk_id=_chunk_id(best),
                score=best.score,
            )
        )
    return citations


def _negated_locator(locator: str) -> tuple[int, ...]:
    """Sort key that makes ``max`` prefer the *ascending* locator on a score tie.

    ``max`` picks the largest key; negating each code point flips the locator
    comparison so the lexicographically smallest locator wins the tie, matching the
    RAG lane's ascending tie-break determinism.
    """
    return tuple(-ord(char) for char in locator)


def dedup_citations(citations: Sequence[Citation]) -> list[Citation]:
    """Return the deduplicated union of citations in first-seen order (Req 6).

    Dedup key is ``(source, locator, chunk_id)`` so the same anchor cited by two
    findings appears once in the report's citation list, deterministically.
    """
    out: list[Citation] = []
    seen: set[tuple[str, str, str]] = set()
    for citation in citations:
        key = (citation.source, citation.locator, citation.chunk_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(citation)
    return out
