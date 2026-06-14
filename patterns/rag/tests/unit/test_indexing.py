"""Index-build + embedding-seam tests for the RAG lane (Req 3.1, 3.2, 6.3).

``build_index`` is the embedding dependency-injection seam: the offline unit lane injects
the deterministic ``HashEmbedding`` fake (content -> sha256 -> fixed-dimension vector) so no
embedding service is contacted (R3.2 / R6.3), while the gated integration lane injects real
Ollama embeddings. The default storage is an in-memory ``SimpleVectorStore`` -- external
vector-store integrations (CVE-2025-1793 SQLi) stay out of scope (R9.1), pinned here so an
upstream default change is caught.
"""

from __future__ import annotations

from llama_index.core.schema import TextNode
from llama_index.core.vector_stores.simple import SimpleVectorStore

from patterns_rag.chunking import ChunkRecord
from patterns_rag.indexing import build_index
from tests.support.fake_embedding import HashEmbedding

_CHUNKS = [
    ChunkRecord(chunk_id="doc::0000", source="doc", locator="page=1", text="alpha beta gamma"),
    ChunkRecord(chunk_id="doc::0001", source="doc", locator="page=2", text="delta epsilon"),
    ChunkRecord(chunk_id="doc::0002", source="doc", locator="section=Intro", text="zeta eta"),
]


# --- HashEmbedding fake (Req 3.2, 6.3): deterministic, offline, fixed dimension ---


def test_hash_embedding_is_deterministic_across_instances() -> None:
    # Two independent instances must embed identical text to the identical vector so the
    # index (and downstream retrieval order) is reproducible run-to-run and machine-to-machine.
    assert HashEmbedding().get_text_embedding("hello") == HashEmbedding().get_text_embedding(
        "hello"
    )


def test_hash_embedding_has_fixed_dimension() -> None:
    embed = HashEmbedding()
    assert len(embed.get_text_embedding("short")) == embed.dim
    assert len(embed.get_text_embedding("a much longer piece of text here")) == embed.dim
    assert len(embed.get_query_embedding("a query")) == embed.dim


def test_hash_embedding_respects_configured_dimension() -> None:
    embed = HashEmbedding(dim=16)
    assert len(embed.get_text_embedding("anything")) == 16


def test_hash_embedding_distinguishes_distinct_texts() -> None:
    # A constant vector would make retrieval meaningless; distinct content must differ.
    assert HashEmbedding().get_text_embedding("alpha") != HashEmbedding().get_text_embedding(
        "omega"
    )


# --- build_index (Req 3.1, 3.2): ChunkRecord -> TextNode, injected embeddings, in-memory store ---


def test_build_index_creates_one_node_per_chunk_keyed_by_chunk_id() -> None:
    index = build_index(_CHUNKS, embed_model=HashEmbedding())
    assert sorted(index.docstore.docs) == ["doc::0000", "doc::0001", "doc::0002"]


def test_build_index_preserves_source_and_locator_metadata() -> None:
    index = build_index(_CHUNKS, embed_model=HashEmbedding())
    node = index.docstore.docs["doc::0001"]
    assert isinstance(node, TextNode)
    assert node.metadata == {"source": "doc", "locator": "page=2"}
    assert node.text == "delta epsilon"


def test_build_index_uses_in_memory_simple_vector_store() -> None:
    # CVE-2025-1793 avoidance: the lane owns an in-memory SimpleVectorStore default (R9.1).
    index = build_index(_CHUNKS, embed_model=HashEmbedding())
    assert isinstance(index.vector_store, SimpleVectorStore)


def test_build_index_embeds_every_chunk_with_injected_model() -> None:
    # The injected model's fixed dimension must appear on every stored vector -- proof the DI
    # seam (not some library default) produced the embeddings (R3.2).
    embed = HashEmbedding(dim=16)
    index = build_index(_CHUNKS, embed_model=embed)
    vector_store = index.vector_store
    assert isinstance(vector_store, SimpleVectorStore)  # narrow base -> .data access
    embedding_dict = vector_store.data.embedding_dict
    assert sorted(embedding_dict) == ["doc::0000", "doc::0001", "doc::0002"]
    assert all(len(vector) == 16 for vector in embedding_dict.values())


def test_build_index_handles_empty_chunk_sequence() -> None:
    # An empty corpus must build cleanly (run_rag turns the empty retrieval into an
    # EmptyCitationError downstream, Task 7) rather than crash here.
    index = build_index([], embed_model=HashEmbedding())
    assert len(index.docstore.docs) == 0
