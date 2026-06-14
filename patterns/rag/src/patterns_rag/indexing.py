"""In-memory vector indexing for the RAG lane (Spec 007-2b Req 3.1, 3.2).

Maps the deterministic ``ChunkRecord`` list produced by :mod:`patterns_rag.chunking` to
LlamaIndex ``TextNode`` objects (``id_`` = ``chunk_id`` so a citation can name a node;
``metadata`` carries ``source`` / ``locator`` so retrieval can reconstruct the
``RetrievedChunk`` contract) and builds a ``VectorStoreIndex`` over them.

The embedding model is a dependency-injection seam (``embed_model``) exactly like the
tokenizer and LLM seams elsewhere in the lane: the offline unit suite injects the
deterministic ``HashEmbedding`` fake (no network, no cached assets), while the gated
integration lane injects real Ollama embeddings (Req 3.2 / 6.3).

Storage is pinned to an in-memory ``SimpleVectorStore``: the lane owns this default rather
than inheriting an upstream one, keeping external vector-store integrations (CVE-2025-1793
SQLi) out of scope (Req 9.1). This module does not own retrieval ordering or answer
generation -- those are :mod:`patterns_rag.retrieval` and :mod:`patterns_rag.rag`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.schema import TextNode
from llama_index.core.vector_stores.simple import SimpleVectorStore

if TYPE_CHECKING:
    from collections.abc import Sequence

    from llama_index.core.base.embeddings.base import BaseEmbedding

    from patterns_rag.chunking import ChunkRecord

__all__ = ["build_index"]


def build_index(chunks: Sequence[ChunkRecord], *, embed_model: BaseEmbedding) -> VectorStoreIndex:
    """Build an in-memory vector index over chunk records using an injected embedding model.

    Args:
        chunks: Deterministic chunk records from :func:`patterns_rag.chunking.chunk_document`.
            May be empty -- an empty corpus yields an empty index (the downstream
            ``run_rag`` turns an empty retrieval into an ``EmptyCitationError``).
        embed_model: The embedding dependency-injection seam. Offline unit runs inject
            ``HashEmbedding``; the gated integration lane injects real Ollama embeddings.

    Returns:
        A ``VectorStoreIndex`` backed by an in-memory ``SimpleVectorStore`` (Req 9.1). Each
        node's ``id_`` is the chunk's ``chunk_id`` and its ``metadata`` carries ``source`` and
        ``locator`` for citation reconstruction at retrieval time.
    """
    nodes = [
        TextNode(
            id_=chunk.chunk_id,
            text=chunk.text,
            metadata={"source": chunk.source, "locator": chunk.locator},
        )
        for chunk in chunks
    ]
    storage_context = StorageContext.from_defaults(vector_store=SimpleVectorStore())
    return VectorStoreIndex(nodes=nodes, storage_context=storage_context, embed_model=embed_model)
