"""Deterministic top-k retrieval tests for the RAG lane (Spec 007-2b Req 3.1, 3.3).

ADR-5: ``retrieve`` re-sorts the retriever's results by ``(-score, chunk_id)`` so equal
scores break by ascending ``chunk_id`` and the top-k order is reproducible run-to-run,
independent of the upstream retriever's internal ordering (NFR-2 flakiness-zero). These
tests pin that order with a stub retriever returning scrambled / tied scores -- no index,
no embeddings, no network.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeWithScore, TextNode
from patterns_contracts import RetrievedChunk

from patterns_rag.retrieval import retrieve

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
    score: float | None,
    *,
    source: str = "doc",
    locator: str = "page=1",
    text: str = "body",
) -> NodeWithScore:
    return NodeWithScore(
        node=TextNode(id_=chunk_id, text=text, metadata={"source": source, "locator": locator}),
        score=score,
    )


def _ids(chunks: list[RetrievedChunk]) -> list[str]:
    return [chunk.chunk_id for chunk in chunks]


def test_retrieve_orders_by_descending_score() -> None:
    # Distinct scores: highest relevance first.
    retriever = _StubRetriever(
        [_node("doc::0000", 0.1), _node("doc::0001", 0.9), _node("doc::0002", 0.5)]
    )
    assert _ids(retrieve(retriever, "q")) == ["doc::0001", "doc::0002", "doc::0000"]


def test_retrieve_breaks_score_ties_by_ascending_chunk_id() -> None:
    # ADR-5 core: identical scores fed in scrambled id order must come out by ascending
    # chunk_id, never by the retriever's incoming order.
    retriever = _StubRetriever(
        [_node("doc::0002", 0.5), _node("doc::0000", 0.5), _node("doc::0001", 0.5)]
    )
    assert _ids(retrieve(retriever, "q")) == ["doc::0000", "doc::0001", "doc::0002"]


def test_retrieve_order_is_independent_of_input_ordering() -> None:
    # Two different incoming orderings of the same node set yield the identical result.
    nodes = [_node("doc::0000", 0.5), _node("doc::0001", 0.9), _node("doc::0002", 0.5)]
    forward = retrieve(_StubRetriever(nodes), "q")
    reversed_ = retrieve(_StubRetriever(list(reversed(nodes))), "q")
    assert _ids(forward) == _ids(reversed_) == ["doc::0001", "doc::0000", "doc::0002"]


def test_retrieve_truncates_to_top_k_after_sorting() -> None:
    # top_k applies to the deterministically sorted list, so the highest-scoring chunks win.
    retriever = _StubRetriever(
        [_node("doc::0000", 0.1), _node("doc::0001", 0.9), _node("doc::0002", 0.5)]
    )
    assert _ids(retrieve(retriever, "q", top_k=2)) == ["doc::0001", "doc::0002"]


def test_retrieve_returns_all_nodes_when_top_k_exceeds_result_count() -> None:
    retriever = _StubRetriever([_node("doc::0000", 0.9), _node("doc::0001", 0.5)])
    assert _ids(retrieve(retriever, "q", top_k=10)) == ["doc::0000", "doc::0001"]


@pytest.mark.parametrize("top_k", [0, -1])
def test_retrieve_rejects_non_positive_top_k(top_k: int) -> None:
    retriever = _StubRetriever([_node("doc::0000", 0.9)])
    with pytest.raises(ValueError, match="top_k"):
        retrieve(retriever, "q", top_k=top_k)


def test_retrieve_reconstructs_retrieved_chunk_from_node_metadata() -> None:
    # node metadata + content + score -> RetrievedChunk contract (Req 3.1).
    retriever = _StubRetriever(
        [_node("doc::0007", 0.42, source="manual", locator="section=2.1", text="grounding text")]
    )
    (chunk,) = retrieve(retriever, "q")
    assert isinstance(chunk, RetrievedChunk)
    assert chunk.chunk_id == "doc::0007"
    assert chunk.source == "manual"
    assert chunk.locator == "section=2.1"
    assert chunk.text == "grounding text"
    assert chunk.score == 0.42


def test_retrieve_treats_missing_score_as_zero() -> None:
    # A retriever may return None scores; they must sort deterministically (as 0.0) rather
    # than crash the (-score, chunk_id) key, and land below any positively-scored chunk.
    retriever = _StubRetriever([_node("doc::0001", None), _node("doc::0000", 0.5)])
    chunks = retrieve(retriever, "q")
    assert _ids(chunks) == ["doc::0000", "doc::0001"]
    assert chunks[1].score == 0.0
