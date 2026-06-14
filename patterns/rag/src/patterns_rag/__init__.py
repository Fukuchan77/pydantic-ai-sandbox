"""Docling + LlamaIndex RAG application lane of the cross-framework patterns.

This package implements a retrieval-augmented generation pipeline that returns
answers with citations anchored to real chunks (Spec 007-2b). The public surface is
flattened here so callers import the entry, contracts, and loud-fail exceptions from one
place (Req 4.1):

* ``run_rag`` -- the only public orchestration entry;
* the shared contract types ``RagAnswer`` / ``Citation`` / ``RetrievedChunk``, re-exported
  from ``patterns_contracts`` so the lane has a single import surface;
* the citation-soundness exceptions ``CitationError`` / ``EmptyCitationError`` /
  ``DanglingCitationError`` that ``run_rag`` raises on ungrounded answers.

The OpenInference tracing helpers (``configure_tracing`` / ``instrument_llamaindex`` /
``uninstrument_llamaindex``) are intentionally *not* re-exported here: by the lane's
boundary discipline they are imported directly from :mod:`patterns_rag.observability`,
keeping this surface to the entry, contracts, and exceptions a caller composes.
"""

from __future__ import annotations

from patterns_contracts import Citation, RagAnswer, RetrievedChunk

from patterns_rag.citation import (
    CitationError,
    DanglingCitationError,
    EmptyCitationError,
)
from patterns_rag.rag import run_rag

__all__ = [
    "Citation",
    "CitationError",
    "DanglingCitationError",
    "EmptyCitationError",
    "RagAnswer",
    "RetrievedChunk",
    "run_rag",
]
