"""Golden + invariant tests for deterministic Docling chunking (Req 2.1-2.3, 4.4, 6.2).

The fixture ``sample.docling.json`` is a *pre-converted* ``DoclingDocument`` so the
heavyweight PDF/OCR converter never touches the CI path (ADR-3); chunking runs the
*real* ``HybridChunker`` against it. Token counting is supplied through the same
dependency-injection seam the embedding/LLM fakes use: a deterministic, fully offline
word tokenizer (the tiktoken default downloads its BPE table on a cold cache, so it is
not hermetic for unit CI -- research.md R-1, finalized here in Task 3). The golden
snapshot in ``golden_chunks.json`` pins chunk boundaries / ``chunk_id`` / ``locator`` so
a dependency bump that shifts grouping is caught as a reviewable diff (R6.2).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from docling_core.transforms.chunker.tokenizer.base import BaseTokenizer
from docling_core.types.doc.document import DoclingDocument
from docling_core.types.doc.labels import DocItemLabel

from patterns_rag.chunking import ChunkRecord, chunk_document, derive_locator

if TYPE_CHECKING:
    from collections.abc import Callable

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_SAMPLE = _FIXTURES / "sample.docling.json"
_GOLDEN = _FIXTURES / "golden_chunks.json"

# Frozen chunking parameters. The golden snapshot is only valid for these exact
# values; changing them requires regenerating golden_chunks.json under diff review.
SOURCE = "rag-overview"
MAX_TOKENS = 32


class WordTokenizer(BaseTokenizer):
    """Deterministic offline tokenizer: one token per whitespace-delimited word.

    Hermetic by construction -- no network, no cached assets, identical counts on every
    machine -- which is exactly what the offline unit lane (R6.1) and a stable golden
    snapshot require. ``get_tokenizer`` returns the bound counter because ``HybridChunker``
    hands it to ``semchunk`` when an oversized chunk must be split.
    """

    max_tokens: int = MAX_TOKENS

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def get_max_tokens(self) -> int:
        return self.max_tokens

    def get_tokenizer(self) -> Callable[[str], int]:
        return self.count_tokens


def _load_doc() -> DoclingDocument:
    return DoclingDocument.load_from_json(_SAMPLE)


def _chunk() -> list[ChunkRecord]:
    return chunk_document(
        _load_doc(), source=SOURCE, tokenizer=WordTokenizer(), max_tokens=MAX_TOKENS
    )


def test_chunk_document_matches_golden() -> None:
    records = [
        {"chunk_id": r.chunk_id, "source": r.source, "locator": r.locator, "text": r.text}
        for r in _chunk()
    ]
    golden = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    assert records == golden


def test_chunking_is_deterministic() -> None:
    # Same input + same token budget -> identical boundaries and ids (R2.2).
    assert _chunk() == _chunk()


def test_chunk_ids_are_ordinal_and_unique() -> None:
    records = _chunk()
    assert [r.chunk_id for r in records] == [f"{SOURCE}::{i:04d}" for i in range(len(records))]
    assert len({r.chunk_id for r in records}) == len(records)  # lane-unique (R2.3)


def test_source_is_injected_on_every_record() -> None:
    assert all(r.source == SOURCE for r in _chunk())


def test_every_record_has_text_and_locator() -> None:
    for r in _chunk():
        assert r.text.strip()
        assert r.locator


def test_repeated_locator_keeps_distinct_chunk_ids() -> None:
    # The split page-3 passages share locator page=3 but must keep unique ids (R2.3).
    records = _chunk()
    by_locator: dict[str, list[str]] = {}
    for r in records:
        by_locator.setdefault(r.locator, []).append(r.chunk_id)
    repeated = {loc: ids for loc, ids in by_locator.items() if len(ids) > 1}
    assert repeated, "fixture is expected to produce at least one split (repeated locator)"
    for ids in repeated.values():
        assert len(set(ids)) == len(ids)


# --- locator derivation priority (ADR-4): page -> section -> char, type-independent ---


def test_derive_locator_prefers_page() -> None:
    assert derive_locator(page_no=3, headings=["Intro"], charspan=(0, 10)) == "page=3"


def test_derive_locator_falls_back_to_section() -> None:
    assert derive_locator(page_no=None, headings=["Method", "Setup"], charspan=None) == (
        "section=Method > Setup"
    )


def test_derive_locator_falls_back_to_char() -> None:
    assert derive_locator(page_no=None, headings=None, charspan=(120, 240)) == "char=120-240"


def test_derive_locator_loud_fails_without_anchor() -> None:
    with pytest.raises(ValueError, match="locator"):
        derive_locator(page_no=None, headings=None, charspan=None)


def test_chunk_without_provenance_falls_back_to_section_locator() -> None:
    # A chunk whose doc items carry no provenance drives `_first_prov` to None, so
    # chunk_document derives the locator from the heading path (ADR-4 section priority)
    # instead of a page/charspan -- prov-less items are tolerated, not a crash (R4.4).
    doc = DoclingDocument(name="no-prov")
    doc.add_heading(text="Synthetic Heading")
    doc.add_text(label=DocItemLabel.TEXT, text="alpha beta gamma delta epsilon")

    records = chunk_document(doc, source="noprov", tokenizer=WordTokenizer(), max_tokens=MAX_TOKENS)

    assert records
    assert all(r.locator == "section=Synthetic Heading" for r in records)


# --- determinism anchor: max_tokens must match the injected tokenizer's budget ---


def test_chunk_document_rejects_tokenizer_budget_mismatch() -> None:
    with pytest.raises(ValueError, match="max_tokens"):
        chunk_document(
            _load_doc(),
            source=SOURCE,
            tokenizer=WordTokenizer(max_tokens=64),
            max_tokens=MAX_TOKENS,
        )


def test_chunk_document_rejects_nonpositive_max_tokens() -> None:
    with pytest.raises(ValueError, match="max_tokens"):
        chunk_document(
            _load_doc(), source=SOURCE, tokenizer=WordTokenizer(max_tokens=0), max_tokens=0
        )
