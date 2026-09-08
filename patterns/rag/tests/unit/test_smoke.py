"""Smoke + hermetic-guard tests for the RAG lane (Spec 007-2b Req 1.1/1.3/1.4, 6.1).

Two concerns live here:

* the lane package imports cleanly and pulls in no sibling lane (NFR-3 / Req 1.3);
* a *fake one-pass* through the whole pipeline -- real ``HybridChunker`` + the deterministic
  ``HashEmbedding`` / ``ScriptedLLM`` fakes -- completes with **zero network I/O** under the
  autouse ``block_network`` guard (``tests/unit/conftest.py``, Req 6.1). ``HF_HUB_OFFLINE=1``
  (set for every unit run via ``pyproject.toml``) keeps the chunker's tokenizer off the Hub;
  the guard proves nothing else slips out either. A load-bearing case proves the guard fires.
"""

from __future__ import annotations

import importlib
import socket
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from docling_core.transforms.chunker.tokenizer.base import BaseTokenizer
from docling_core.types.doc.document import DoclingDocument

from patterns_rag.chunking import chunk_document
from patterns_rag.indexing import build_index
from patterns_rag.rag import run_rag
from tests.support.fake_embedding import HashEmbedding
from tests.support.fake_llm import ScriptedLLM
from tests.support.hermetic import NetworkReachError

if TYPE_CHECKING:
    from collections.abc import Callable

# Sibling lanes the RAG lane must never import (NFR-3 / Req 1.3). Contract
# sharing is allowed and flows only through the `patterns_contracts` path
# dependency, which is intentionally absent from this set.
SIBLING_LANES = frozenset({"patterns_pydantic_ai", "patterns_beeai", "patterns_llamaindex"})

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sample.docling.json"


def test_patterns_rag_imports() -> None:
    import patterns_rag

    assert patterns_rag.__name__ == "patterns_rag"


def test_no_sibling_lane_imports() -> None:
    # Import for its side effect: populate sys.modules without binding a name
    # (keeps pyright strict's reportUnusedImport quiet).
    importlib.import_module("patterns_rag")

    leaked = SIBLING_LANES & set(sys.modules)
    assert not leaked, f"RAG lane must not import sibling lanes: {sorted(leaked)}"


class _WordTokenizer(BaseTokenizer):
    """Deterministic offline tokenizer (one token per whitespace word) for the one-pass.

    Hermetic by construction -- no network, no cached assets -- so ``HybridChunker`` can run
    without the tiktoken/HF download the real tokenizers trigger on a cold cache (research.md
    R-1). The exact budget is irrelevant here: the one-pass asserts hermeticity, not golden
    boundaries (those are pinned in ``test_chunking_golden``).
    """

    max_tokens: int = 64

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def get_max_tokens(self) -> int:
        return self.max_tokens

    def get_tokenizer(self) -> Callable[[str], int]:
        return self.count_tokens


def test_block_network_guard_loud_fails_on_internet_connect() -> None:
    # Load-bearing proof the autouse guard is not vacuous: a real AF_INET connect must be
    # intercepted before any I/O (a loopback closed port would otherwise raise
    # ConnectionRefusedError).
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock,
        pytest.raises(NetworkReachError),
    ):
        sock.connect(("127.0.0.1", 9))


async def test_fake_one_pass_runs_hermetically() -> None:
    # Full pipeline under the guard: real chunker -> fake embeddings -> real retriever ->
    # fake LLM, all offline. Reaching the network anywhere raises NetworkReachError (Req 6.1).
    doc = DoclingDocument.load_from_json(_FIXTURE)
    chunks = chunk_document(doc, source="smoke", tokenizer=_WordTokenizer(), max_tokens=64)
    index = build_index(chunks, embed_model=HashEmbedding())
    retriever = index.as_retriever(similarity_top_k=4)
    answer = await run_rag("what is rag?", llm=ScriptedLLM(answer="grounded"), retriever=retriever)

    assert answer.answer == "grounded"
    assert answer.citations  # the fake echoes retrieved chunks, so the answer is grounded
