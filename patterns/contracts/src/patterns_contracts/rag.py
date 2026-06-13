"""RAG application-layer contracts (Spec 007-2b Req 4.1, 5.1).

This module is the single source of truth for the RAG pattern's retrieval and
answer Pydantic models; the normative copy also lives in
``patterns/rag/README.md`` fenced block, asserted equal by the single-point
drift test once the ``rag`` README is registered. The RAG lane (``patterns_rag``)
imports these via the ``patterns/contracts`` path dependency rather than
duplicating them (NFR-3).

RAG is the first *application layer* contract (not one of the six workflow
patterns): a ``locator`` is a document-type-independent anchor string (e.g.
``page=3`` / ``section=2.1`` / ``char=120-240``, ADR-4) and ``chunk_id`` is the
deterministic key (``f"{source}::{ordinal:04d}"``) a ``Citation`` must point at.
The >=1-citation invariant (Req 4.2) and dangling-citation loud-fail (Req 4.3)
are enforced in the RAG pipeline (``rag.citation``), not as field constraints
here -- the contract stays a plain, dependency-zero shape.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = [
    "Citation",
    "RagAnswer",
    "RetrievedChunk",
]


class RetrievedChunk(BaseModel):
    """A chunk returned by top-k retrieval, carrying its source anchor and score."""

    chunk_id: str = Field(description="Lane-unique deterministic key (f'{source}::{ordinal:04d}').")
    source: str = Field(description="Document identifier the chunk was derived from.")
    locator: str = Field(
        description="Document-type-independent anchor (e.g. page=3 / char=120-240)."
    )
    text: str = Field(description="The chunk text used to ground an answer.")
    score: float = Field(description="Retrieval score; ties break by ascending chunk_id (R3.3).")


class Citation(BaseModel):
    """A source anchor backing one claim in the answer; must point at a real chunk."""

    source: str = Field(description="Document identifier of the cited chunk.")
    locator: str = Field(description="Anchor within the source the citation refers to (R4.4).")
    chunk_id: str = Field(
        description="chunk_id of a retrieved chunk; dangling values loud-fail (R4.3)."
    )
    score: float = Field(description="Retrieval score of the backing chunk.")


class RagAnswer(BaseModel):
    """Final RAG output: an answer with the citations that ground it (>=1, R4.2)."""

    answer: str = Field(description="Answer text generated from the retrieved chunks.")
    citations: list[Citation] = Field(
        description="Citations backing the answer (>=1 enforced by pipeline)."
    )
