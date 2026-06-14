"""Deterministic Docling chunking for the RAG lane (Spec 007-2b Req 2.1-2.3, 4.4).

Wraps the *real* docling-core ``HybridChunker`` so a pre-converted ``DoclingDocument``
(the heavyweight converter stays off the CI path -- ADR-3) is split into a deterministic
list of ``ChunkRecord`` objects, each carrying the provenance a citation points back at:

* ``source`` -- injected by the caller (more robust than reading ``meta.origin`` for
  fixtures, ADR-4).
* ``chunk_id`` -- ``f"{source}::{ordinal:04d}"``; the ordinal is the chunk's position in
  the deterministic chunking order, so ids are lane-unique even when two chunks share a
  locator (R2.3).
* ``locator`` -- a document-type-independent anchor string derived by the ADR-4 priority
  ``page -> section -> char`` (R4.4).

Token counting is a dependency-injection seam (``tokenizer``) exactly like the embedding
and LLM seams elsewhere in the lane: the offline unit suite injects a deterministic word
tokenizer rather than tiktoken, whose BPE table downloads on a cold cache and would break
hermetic CI (research.md R-1, finalized in Task 3). ``max_tokens`` is passed explicitly as
a determinism anchor and validated against the tokenizer's own budget so a mismatched
tokenizer cannot silently shift chunk boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from docling_core.transforms.chunker.doc_chunk import DocMeta
from docling_core.transforms.chunker.hybrid_chunker import HybridChunker

if TYPE_CHECKING:
    from collections.abc import Sequence

    from docling_core.transforms.chunker.tokenizer.base import BaseTokenizer
    from docling_core.types.doc.document import DoclingDocument, ProvenanceItem

__all__ = ["ChunkRecord", "chunk_document", "derive_locator"]


@dataclass(frozen=True, slots=True)
class ChunkRecord:
    """A lane-internal chunk: deterministic id, injected source, anchor, and text.

    This is intentionally a plain dataclass, not a contract model -- it never crosses the
    package boundary. ``build_index`` (Task 4) maps it to a LlamaIndex ``TextNode`` and the
    contract ``RetrievedChunk`` is reconstructed at retrieval time.
    """

    chunk_id: str
    source: str
    locator: str
    text: str


def derive_locator(
    *, page_no: int | None, headings: Sequence[str] | None, charspan: tuple[int, int] | None
) -> str:
    """Build a document-type-independent locator by the ADR-4 priority (R4.4).

    Priority: a page number (PDF-like sources) wins; otherwise a heading path
    (Markdown-like sources); otherwise a character span. A chunk with none of these has no
    anchor a citation could correspond to, so it loud-fails rather than emit a meaningless
    locator.

    Args:
        page_no: 1-based page number of the chunk's first provenance, if any.
        headings: Heading path enclosing the chunk, if any.
        charspan: ``(start, end)`` character offsets of the chunk's first provenance.

    Returns:
        A locator string such as ``page=3`` / ``section=Method > Setup`` / ``char=120-240``.

    Raises:
        ValueError: If no page, heading, or character span is available.
    """
    if page_no is not None:
        return f"page={page_no}"
    if headings:
        return "section=" + " > ".join(headings)
    if charspan is not None:
        return f"char={charspan[0]}-{charspan[1]}"
    msg = "chunk has no derivable locator (no page, heading, or charspan)"
    raise ValueError(msg)


def _first_prov(meta: DocMeta) -> ProvenanceItem | None:
    """Return the first provenance item across the chunk's doc items, if any."""
    for item in meta.doc_items:
        if item.prov:
            return item.prov[0]
    return None


def chunk_document(
    doc: DoclingDocument, *, source: str, tokenizer: BaseTokenizer, max_tokens: int
) -> list[ChunkRecord]:
    """Chunk a pre-converted ``DoclingDocument`` into deterministic ``ChunkRecord`` objects.

    Runs the real ``HybridChunker`` (default merge/split behaviour) and derives
    ``source`` / ``locator`` / ``chunk_id`` for each emitted chunk (R2.1). The same document
    and token budget always yield the same boundaries and ids (R2.2).

    Args:
        doc: A pre-converted Docling document (converter kept off the CI path, ADR-3).
        source: Document identifier injected into every chunk's id and ``source`` field.
        tokenizer: Token-counting seam handed to ``HybridChunker``; its ``get_max_tokens``
            must equal ``max_tokens``.
        max_tokens: Explicit token-budget determinism anchor.

    Returns:
        The chunks in deterministic chunking order.

    Raises:
        ValueError: If ``max_tokens`` is below 1, or the tokenizer's budget differs from it.
    """
    if max_tokens < 1:
        msg = f"max_tokens must be >= 1, got {max_tokens}"
        raise ValueError(msg)
    if tokenizer.get_max_tokens() != max_tokens:
        msg = (
            f"tokenizer budget ({tokenizer.get_max_tokens()}) must equal max_tokens "
            f"({max_tokens}) so chunk boundaries stay deterministic"
        )
        raise ValueError(msg)

    chunker = HybridChunker(tokenizer=tokenizer)
    records: list[ChunkRecord] = []
    for ordinal, chunk in enumerate(chunker.chunk(doc)):
        meta = chunk.meta
        if not isinstance(meta, DocMeta):  # pragma: no cover - HybridChunker always emits DocChunk
            msg = f"expected DocMeta from HybridChunker, got {type(meta).__name__}"
            raise TypeError(msg)
        prov = _first_prov(meta)
        locator = derive_locator(
            page_no=prov.page_no if prov is not None else None,
            headings=meta.headings,
            charspan=prov.charspan if prov is not None else None,
        )
        records.append(
            ChunkRecord(
                chunk_id=f"{source}::{ordinal:04d}",
                source=source,
                locator=locator,
                text=chunker.contextualize(chunk),
            )
        )
    return records
