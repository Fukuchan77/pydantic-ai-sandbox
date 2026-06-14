"""Dangling / empty citation loud-fail tests for the RAG lane (Spec 007-2b Req 4.2, 4.3, 9.3).

``validate_citations`` is the contract-level defense against ungrounded answers. It must
loud-fail on the two ways grounding breaks rather than passing them silently downstream:
an answer with zero citations (Req 4.2) and a citation whose ``chunk_id`` points at no
retrieved chunk -- the "citation spoofing" failure mode (Req 4.3 / R9.3). These tests pin
those raises with plain contract objects; no index, no LLM, no network.
"""

from __future__ import annotations

import pytest
from patterns_contracts import Citation, RagAnswer, RetrievedChunk

from patterns_rag.citation import (
    CitationError,
    DanglingCitationError,
    EmptyCitationError,
    validate_citations,
)


def _chunk(chunk_id: str, *, source: str = "doc", locator: str = "page=1") -> RetrievedChunk:
    return RetrievedChunk(chunk_id=chunk_id, source=source, locator=locator, text="body", score=0.5)


def _citation(chunk_id: str, *, source: str = "doc", locator: str = "page=1") -> Citation:
    return Citation(source=source, locator=locator, chunk_id=chunk_id, score=0.5)


def test_validate_citations_accepts_citations_pointing_at_retrieved_chunks() -> None:
    # Happy path: a citation whose chunk_id is in the retrieved set is sound -> no raise.
    retrieved = [_chunk("doc::0000"), _chunk("doc::0001")]
    answer = RagAnswer(answer="grounded", citations=[_citation("doc::0000")])
    validate_citations(answer, retrieved)


def test_validate_citations_raises_on_empty_citations() -> None:
    # Req 4.2: an answer with no citations is forbidden.
    answer = RagAnswer(answer="ungrounded", citations=[])
    with pytest.raises(EmptyCitationError):
        validate_citations(answer, [_chunk("doc::0000")])


def test_validate_citations_raises_on_dangling_chunk_id() -> None:
    # Req 4.3 / R9.3: a citation pointing at a chunk that was never retrieved is spoofing.
    answer = RagAnswer(answer="spoofed", citations=[_citation("doc::9999")])
    with pytest.raises(DanglingCitationError, match="doc::9999"):
        validate_citations(answer, [_chunk("doc::0000")])


def test_validate_citations_treats_every_citation_as_dangling_when_retrieved_is_empty() -> None:
    # With nothing retrieved, any citation is dangling (precedes only the empty-citation check).
    answer = RagAnswer(answer="spoofed", citations=[_citation("doc::0000")])
    with pytest.raises(DanglingCitationError):
        validate_citations(answer, [])


def test_validate_citations_reports_all_dangling_chunk_ids() -> None:
    # Loud-fail is informative: every offending id is named, not just the first encountered.
    answer = RagAnswer(
        answer="spoofed",
        citations=[_citation("doc::0000"), _citation("doc::8888"), _citation("doc::9999")],
    )
    with pytest.raises(DanglingCitationError) as exc_info:
        validate_citations(answer, [_chunk("doc::0000")])
    message = str(exc_info.value)
    assert "doc::8888" in message
    assert "doc::9999" in message


def test_empty_citation_check_precedes_dangling_check() -> None:
    # An empty answer against an empty retrieved set is an EmptyCitationError, not dangling.
    answer = RagAnswer(answer="ungrounded", citations=[])
    with pytest.raises(EmptyCitationError):
        validate_citations(answer, [])


def test_citation_errors_share_a_common_base_class() -> None:
    # A single ``except CitationError`` lets the orchestrator (Task 7) catch either failure.
    assert issubclass(EmptyCitationError, CitationError)
    assert issubclass(DanglingCitationError, CitationError)
