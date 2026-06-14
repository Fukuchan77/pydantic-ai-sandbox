"""Citation soundness tests for the RAG lane (Spec 007-2b Req 6.4, 4.4).

Req 6.4 requires a soundness test asserting that every ``Citation`` points at a real
retrieved chunk and that its ``locator`` corresponds to that chunk's source range. These
tests build citations faithfully from a retrieved set and lock the resolution invariant:
each citation resolves to exactly one chunk by ``chunk_id`` with a matching source/locator
anchor, and ``validate_citations`` accepts the sound answer. The locator is a
document-type-independent string (Req 4.4), so soundness must hold across anchor styles.
Offline, no LLM, no network.
"""

from __future__ import annotations

import pytest
from patterns_contracts import Citation, RagAnswer, RetrievedChunk

from patterns_rag.citation import validate_citations


def _retrieved() -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            chunk_id="manual::0000", source="manual", locator="page=1", text="intro", score=0.9
        ),
        RetrievedChunk(
            chunk_id="manual::0001", source="manual", locator="section=2.1", text="setup", score=0.7
        ),
        RetrievedChunk(
            chunk_id="manual::0002",
            source="manual",
            locator="char=120-240",
            text="usage",
            score=0.4,
        ),
    ]


def _faithful_citation(chunk: RetrievedChunk) -> Citation:
    # A faithful citation mirrors the chunk's anchor: same source, locator, and chunk_id.
    return Citation(
        source=chunk.source, locator=chunk.locator, chunk_id=chunk.chunk_id, score=chunk.score
    )


def test_each_citation_resolves_to_a_real_chunk_with_matching_anchor() -> None:
    retrieved = _retrieved()
    by_id = {chunk.chunk_id: chunk for chunk in retrieved}
    answer = RagAnswer(
        answer="grounded",
        citations=[_faithful_citation(retrieved[0]), _faithful_citation(retrieved[2])],
    )

    validate_citations(answer, retrieved)  # sound answer must not raise

    for citation in answer.citations:
        # Req 6.4: each citation points at an existing retrieved chunk...
        assert citation.chunk_id in by_id
        chunk = by_id[citation.chunk_id]
        # ...and its source / locator correspond to that chunk's source range (Req 4.4, 6.4).
        assert citation.source == chunk.source
        assert citation.locator == chunk.locator


@pytest.mark.parametrize("locator", ["page=3", "section=2.1", "char=120-240"])
def test_soundness_holds_across_locator_styles(locator: str) -> None:
    # Req 4.4: locator is document-type-independent; soundness must not depend on its shape.
    chunk = RetrievedChunk(
        chunk_id="doc::0000", source="doc", locator=locator, text="body", score=0.5
    )
    answer = RagAnswer(answer="grounded", citations=[_faithful_citation(chunk)])

    validate_citations(answer, [chunk])

    assert answer.citations[0].locator == locator
