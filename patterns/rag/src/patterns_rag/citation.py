"""Citation soundness and loud-fail for the RAG lane (Spec 007-2b Req 4.2, 4.3, 9.3).

A RAG answer is only trustworthy if every claim it cites is grounded in a chunk the
retriever actually returned. This module is the contract-level defense against the two ways
that grounding breaks: an answer with no citations at all (Req 4.2) and a citation whose
``chunk_id`` points at no retrieved chunk -- a *dangling* citation, the "citation spoofing"
failure mode (Req 4.3 / R9.3). Both loud-fail with a dedicated exception rather than
passing silently downstream, where a fabricated source could be mistaken for grounded.

This module does not own answer generation (:mod:`patterns_rag.rag`) or retrieval
(:mod:`patterns_rag.retrieval`); it validates an already-produced ``RagAnswer`` against the
chunks that were retrieved to ground it. ``chunk_id`` membership is the soundness key --
``chunk_id`` is lane-unique, so a citation is grounded iff its id is in the retrieved set.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from patterns_contracts import RagAnswer, RetrievedChunk

__all__ = [
    "CitationError",
    "DanglingCitationError",
    "EmptyCitationError",
    "validate_citations",
]


class CitationError(Exception):
    """Base class for citation-soundness violations that loud-fail a RAG answer."""


class EmptyCitationError(CitationError):
    """Raised when a ``RagAnswer`` carries no citations (Req 4.2)."""


class DanglingCitationError(CitationError):
    """Raised when a ``Citation.chunk_id`` matches no retrieved chunk (Req 4.3 / R9.3)."""


def validate_citations(answer: RagAnswer, retrieved: Sequence[RetrievedChunk]) -> None:
    """Validate that ``answer``'s citations are non-empty and all point at retrieved chunks.

    Args:
        answer: The generated answer whose citations must be grounded.
        retrieved: The chunks returned by retrieval that the answer was grounded in.

    Raises:
        EmptyCitationError: If ``answer`` carries no citations (Req 4.2). Checked first, so an
            empty answer against an empty retrieved set fails as empty, not dangling.
        DanglingCitationError: If any citation's ``chunk_id`` is absent from ``retrieved``
            (Req 4.3 / R9.3); the message names every dangling id and the known chunk ids.
    """
    if not answer.citations:
        raise EmptyCitationError("RagAnswer must carry at least one citation, got none.")
    known = {chunk.chunk_id for chunk in retrieved}
    dangling = sorted({c.chunk_id for c in answer.citations if c.chunk_id not in known})
    if dangling:
        raise DanglingCitationError(
            f"Citation chunk_id(s) {dangling} not in retrieved set {sorted(known)}."
        )
