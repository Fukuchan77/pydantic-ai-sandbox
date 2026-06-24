"""Citation grounding tests for the Deep Research lane (Spec 009 Req 5, 6).

Every citation a finding carries must point at a source the researcher actually
retrieved (the RAG citation-soundness discipline applied to research). A finding
that cites nothing loud-fails ``EmptyCitationError``; a finding citing an
unretrieved source loud-fails ``DanglingCitationError``. The report's citation
list is the deduplicated union across findings.
"""

from __future__ import annotations

import pytest
from patterns_contracts import Citation, SearchResult, SubQuestion

from patterns_deep_research import DanglingCitationError, EmptyCitationError
from patterns_deep_research.compression import dedup_citations, map_citations
from patterns_deep_research.researcher import run_subquestion
from tests.support.fake_search import FakeSearchProvider
from tests.support.model_fakes import scripted_model

_SUBQUESTION = SubQuestion(description="What is the lead agent's role?")

_RESULTS = [
    SearchResult(source="a", locator="url=a", snippet="alpha", score=0.9),
    SearchResult(source="a", locator="url=a2", snippet="alpha-2", score=0.95),
    SearchResult(source="b", locator="url=b", snippet="beta", score=0.5),
]


def test_map_citations_grounds_chosen_sources() -> None:
    citations = map_citations(["a", "b"], _RESULTS)
    by_source = {c.source: c for c in citations}
    # For source "a", the highest-scoring result (url=a2, 0.95) is the anchor.
    assert by_source["a"].locator == "url=a2"
    assert by_source["a"].chunk_id == "a::url=a2"
    assert by_source["b"].chunk_id == "b::url=b"


def test_map_citations_dedupes_repeated_source() -> None:
    citations = map_citations(["a", "a"], _RESULTS)
    assert len(citations) == 1


def test_empty_citation_loud_fails() -> None:
    with pytest.raises(EmptyCitationError):
        map_citations([], _RESULTS)


def test_dangling_citation_loud_fails() -> None:
    with pytest.raises(DanglingCitationError, match="ghost"):
        map_citations(["ghost"], _RESULTS)


def test_dedup_citations_union_first_seen_order() -> None:
    c1 = Citation(source="a", locator="url=a", chunk_id="a::url=a", score=0.9)
    c2 = Citation(source="b", locator="url=b", chunk_id="b::url=b", score=0.5)
    deduped = dedup_citations([c1, c2, c1])
    assert [c.source for c in deduped] == ["a", "b"]


async def test_researcher_empty_corpus_loud_fails() -> None:
    # No results gathered + a scripted finding that cites nothing -> EmptyCitationError.
    model = scripted_model(
        action={"query": "q", "enough": True},
        finding={"summary": "no grounding", "cited_sources": []},
    )
    with pytest.raises(EmptyCitationError):
        await run_subquestion(
            _SUBQUESTION, model=model, search=FakeSearchProvider(force_empty=True), max_iterations=1
        )


async def test_researcher_fabricated_source_loud_fails() -> None:
    # A scripted finding citing a source absent from the corpus -> DanglingCitationError.
    model = scripted_model(
        action={"query": "q", "enough": True},
        finding={"summary": "fabricated", "cited_sources": ["does-not-exist"]},
    )
    with pytest.raises(DanglingCitationError):
        await run_subquestion(
            _SUBQUESTION, model=model, search=FakeSearchProvider(), max_iterations=1
        )
