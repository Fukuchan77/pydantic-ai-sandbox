"""``run_rag`` orchestration contract tests for the RAG lane (Spec 007-2b Req 4.1, 4.2, 4.3).

``run_rag`` is the lane's only public entry: it retrieves, builds a chunk-labelled prompt,
asks the injected LLM for a structured ``RagAnswer``, and validates the answer's citations
before returning. These tests pin that control flow offline with the scripted LLM fake and a
stub retriever -- no index, no embeddings, no network:

* the happy path returns a ``RagAnswer`` whose citations are all grounded in the retrieved
  set and respects ``top_k`` (Req 4.1);
* an empty index (zero retrieved chunks) loud-fails as ``EmptyCitationError`` (Req 4.2,
  plan §Error Handling);
* a hallucinated citation loud-fails as ``DanglingCitationError``, proving the
  ``validate_citations`` call is load-bearing rather than decorative (Req 4.3 / R9.3);
* a non-positive ``top_k`` is rejected at the boundary (inherited from ``retrieve``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeWithScore, TextNode
from patterns_contracts import Citation, RagAnswer

from patterns_rag.citation import DanglingCitationError, EmptyCitationError
from patterns_rag.rag import run_rag
from tests.support.fake_llm import ScriptedLLM

if TYPE_CHECKING:
    from llama_index.core.schema import QueryBundle


class _StubRetriever(BaseRetriever):
    """Returns a fixed ``NodeWithScore`` list, ignoring the query (offline determinism)."""

    def __init__(self, scored_nodes: list[NodeWithScore]) -> None:
        # llama-index BaseRetriever.__init__ is untyped upstream (Dict without type args), so
        # strict pyright cannot fully resolve the super() call -- the runtime call is required
        # for callback_manager setup that retrieve() relies on.
        super().__init__()  # pyright: ignore[reportUnknownMemberType]
        self._scored_nodes = scored_nodes

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        return self._scored_nodes


def _node(
    chunk_id: str,
    score: float,
    *,
    source: str = "doc",
    locator: str = "page=1",
    text: str = "grounding body",
) -> NodeWithScore:
    return NodeWithScore(
        node=TextNode(id_=chunk_id, text=text, metadata={"source": source, "locator": locator}),
        score=score,
    )


def _two_chunk_retriever() -> _StubRetriever:
    return _StubRetriever(
        [_node("doc::0000", 0.5, locator="page=1"), _node("doc::0001", 0.9, locator="page=2")]
    )


async def test_run_rag_returns_rag_answer_grounded_in_retrieved_chunks() -> None:
    # Every citation must name a chunk the retriever actually returned (grounding, Req 4.1).
    retriever = _two_chunk_retriever()
    result = await run_rag("q", llm=ScriptedLLM(answer="the answer"), retriever=retriever)

    assert isinstance(result, RagAnswer)
    assert result.answer == "the answer"
    assert result.citations
    assert all(isinstance(c, Citation) for c in result.citations)
    assert {c.chunk_id for c in result.citations} <= {"doc::0000", "doc::0001"}


async def test_run_rag_citation_carries_retrieved_chunk_metadata() -> None:
    # The labelled prompt round-trips source/locator/chunk_id back into each citation.
    retriever = _StubRetriever(
        [_node("manual::0007", 0.42, source="manual", locator="section=2.1")]
    )
    result = await run_rag("q", llm=ScriptedLLM(), retriever=retriever)

    (citation,) = result.citations
    assert citation.chunk_id == "manual::0007"
    assert citation.source == "manual"
    assert citation.locator == "section=2.1"
    assert citation.score == 0.42


async def test_run_rag_honors_top_k() -> None:
    # top_k caps the chunks that reach the prompt, so only top_k chunks can be cited.
    retriever = _StubRetriever(
        [_node("doc::0000", 0.1), _node("doc::0001", 0.9), _node("doc::0002", 0.5)]
    )
    result = await run_rag("q", llm=ScriptedLLM(), retriever=retriever, top_k=2)

    assert {c.chunk_id for c in result.citations} == {"doc::0001", "doc::0002"}


async def test_run_rag_empty_index_loud_fails_as_empty_citation_error() -> None:
    # Zero retrieved chunks -> nothing to cite -> EmptyCitationError (plan §Error Handling).
    retriever = _StubRetriever([])
    with pytest.raises(EmptyCitationError):
        await run_rag("q", llm=ScriptedLLM(), retriever=retriever)


async def test_run_rag_loud_fails_on_dangling_citation() -> None:
    # A hallucinated chunk_id must be caught by run_rag's validate_citations (Req 4.3 / R9.3).
    retriever = _two_chunk_retriever()
    llm = ScriptedLLM(dangling_chunk_id="doc::9999")
    with pytest.raises(DanglingCitationError, match="doc::9999"):
        await run_rag("q", llm=llm, retriever=retriever)


@pytest.mark.parametrize("top_k", [0, -1])
async def test_run_rag_rejects_non_positive_top_k(top_k: int) -> None:
    retriever = _two_chunk_retriever()
    with pytest.raises(ValueError, match="top_k"):
        await run_rag("q", llm=ScriptedLLM(), retriever=retriever, top_k=top_k)
