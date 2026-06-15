"""Gated Ollama integration test for the RAG lane (Spec 007-2b Req 7.1-7.3).

Skipped unless ``RUN_INTEGRATION_PATTERNS=1`` (Req 7.1). The single end-to-end test drives
the *real* Ollama path -- real embeddings build the in-memory index and a real Ollama LLM
generates the cited answer -- and asserts only at the **contract** level (Req 7.2): the
answer carries >=1 citation, every citation names a source and chunk that were actually
indexed, and the prose is non-empty. Exact text is never asserted because a live model is
non-deterministic. Model identity comes exclusively from the environment (Req 7.3):
``OLLAMA_MODEL_NAME`` / ``OLLAMA_EMBED_MODEL_NAME`` / ``OLLAMA_BASE_URL``.

Chunking stays provider-independent and offline: the real ``HybridChunker`` runs with a
deterministic word tokenizer so it never reaches the HF Hub (``HF_HUB_OFFLINE=1`` is forced
for every run, including this lane). Only embedding and generation touch Ollama.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from docling_core.transforms.chunker.tokenizer.base import BaseTokenizer
from docling_core.types.doc.document import DoclingDocument

from patterns_rag import RagAnswer, run_rag
from patterns_rag.chunking import chunk_document
from patterns_rag.indexing import build_index

if TYPE_CHECKING:
    from collections.abc import Callable

    from llama_index.core.base.embeddings.base import BaseEmbedding
    from llama_index.core.llms import LLM

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_PATTERNS") != "1",
    reason="integration lane gated by RUN_INTEGRATION_PATTERNS=1",
)

# The pre-converted Docling fixture shared with the offline unit suite (ADR-3): the
# heavyweight converter stays off every code path, integration included.
_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sample.docling.json"

# Source identifier injected into every chunk's id and ``source`` field. Citations must name
# this back, so it is the "known source" set the contract assertions check against (Req 7.2).
_SOURCE = "ollama-e2e"

_MAX_TOKENS = 64


class _WordTokenizer(BaseTokenizer):
    """Deterministic offline tokenizer (one token per whitespace word) for ``HybridChunker``.

    Chunking is provider-independent; using this instead of tiktoken/HF keeps the chunker off
    the network even in the gated lane (``HF_HUB_OFFLINE=1`` is forced for every run). The
    exact budget is immaterial -- the integration test asserts the live Ollama contract, not
    golden chunk boundaries (those are pinned in the offline ``test_chunking_golden``).
    """

    max_tokens: int = _MAX_TOKENS

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def get_max_tokens(self) -> int:
        return self.max_tokens

    def get_tokenizer(self) -> Callable[[str], int]:
        return self.count_tokens


def _base_url() -> str:
    """Return the Ollama daemon root, stripping the repo-wide OpenAI-style ``/v1`` suffix.

    The llama-index Ollama clients expect the daemon root URL, but the repo convention exposes
    ``OLLAMA_BASE_URL`` as an OpenAI-style base ending in ``/v1`` (sibling llamaindex lane).
    """
    return os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1").removesuffix("/v1")


def _ollama_embedding() -> BaseEmbedding:
    from llama_index.embeddings.ollama import (  # pyright: ignore[reportMissingTypeStubs]
        OllamaEmbedding,
    )

    return OllamaEmbedding(model_name=os.environ["OLLAMA_EMBED_MODEL_NAME"], base_url=_base_url())


def _ollama_llm() -> LLM:
    from llama_index.llms.ollama import Ollama  # pyright: ignore[reportMissingTypeStubs]

    # context_window bounds the Ollama num_ctx: llama-index's default requests the
    # model's full context (num_ctx=131072 for granite4.1), whose KV cache (~20 GB)
    # OOMs the CPU runner's llama-server with a 500. 8192 tokens is ample for the
    # short contract-level RAG prompt (4 retrieved chunks + template) and keeps the
    # KV cache within the runner's memory. num_predict caps generation so the cited
    # answer returns promptly; request_timeout matches the sibling lanes' headroom
    # for slow CPU structured-predict. (Same OOM class fixed in the llamaindex lane.)
    return Ollama(
        model=os.environ["OLLAMA_MODEL_NAME"],
        base_url=_base_url(),
        request_timeout=1200.0,
        context_window=8192,
        additional_kwargs={"num_predict": 512},
    )


async def test_run_rag_against_live_ollama() -> None:
    # Real path: real chunker (offline tokenizer) -> real Ollama embeddings -> real retriever
    # -> real Ollama LLM. Assertions stay at the contract level (Req 7.2); run_rag itself
    # loud-fails an empty or dangling citation set, so reaching the asserts already proves
    # grounding -- the asserts pin that contract explicitly and verify each source is known.
    doc = DoclingDocument.load_from_json(_FIXTURE)
    chunks = chunk_document(doc, source=_SOURCE, tokenizer=_WordTokenizer(), max_tokens=_MAX_TOKENS)
    known_chunk_ids = {chunk.chunk_id for chunk in chunks}

    index = build_index(chunks, embed_model=_ollama_embedding())
    retriever = index.as_retriever(similarity_top_k=4)

    answer = await run_rag("What is this document about?", llm=_ollama_llm(), retriever=retriever)

    assert isinstance(answer, RagAnswer)
    assert answer.answer.strip()  # non-empty prose, but never an exact-text match
    assert answer.citations, "a grounded answer must carry >=1 citation (Req 7.2)"
    for citation in answer.citations:
        assert citation.source == _SOURCE, "each citation must name the indexed source (Req 7.2)"
        assert citation.chunk_id in known_chunk_ids, "each citation must name an indexed chunk"
