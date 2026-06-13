"""Behavioral shape contract for the RAG models (Spec 007-2b Req 4.1, 5.1).

Complements the AST/introspection parity in ``test_contract_drift.py`` by
exercising the three RAG contracts at runtime: that they re-export from the
package root (Req 5.1), expose exactly the fields declared in Req 4.1, and that
``RagAnswer`` nests ``Citation`` so a JSON-shaped payload round-trips through
validation. Field-level constraints (e.g. the >=1 citation invariant) are
deliberately *not* asserted here -- that loud-fail lives in the RAG pipeline
(``rag.citation``), not the dependency-zero contract.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from patterns_contracts import Citation, RagAnswer, RetrievedChunk


def test_rag_models_reexport_from_package_root() -> None:
    # Req 5.1: consumers depend on the flat, submodule-agnostic import path.
    for model in (RetrievedChunk, Citation, RagAnswer):
        assert issubclass(model, BaseModel)
    for name in ("RetrievedChunk", "Citation", "RagAnswer"):
        assert name in __import__("patterns_contracts").__all__


def test_retrieved_chunk_field_set() -> None:
    # Req 4.1: RetrievedChunk{chunk_id, source, locator, text, score}.
    assert set(RetrievedChunk.model_fields) == {"chunk_id", "source", "locator", "text", "score"}


def test_citation_field_set() -> None:
    # Req 4.1: Citation{source, locator, chunk_id, score}.
    assert set(Citation.model_fields) == {"source", "locator", "chunk_id", "score"}


def test_rag_answer_field_set() -> None:
    # Req 4.1: RagAnswer{answer, citations}.
    assert set(RagAnswer.model_fields) == {"answer", "citations"}


def test_retrieved_chunk_roundtrips() -> None:
    chunk = RetrievedChunk(
        chunk_id="doc::0001",
        source="doc",
        locator="page=3",
        text="the retrieved passage",
        score=0.87,
    )
    assert chunk.chunk_id == "doc::0001"
    assert isinstance(chunk.score, float)


def test_rag_answer_nests_citation_from_payload() -> None:
    # Req 4.1: RagAnswer.citations is list[Citation]; a dict payload coerces.
    answer = RagAnswer.model_validate(
        {
            "answer": "grounded answer",
            "citations": [
                {"source": "doc", "locator": "page=3", "chunk_id": "doc::0001", "score": 0.9},
            ],
        }
    )
    assert len(answer.citations) == 1
    assert isinstance(answer.citations[0], Citation)
    assert answer.citations[0].chunk_id == "doc::0001"


def test_citation_rejects_missing_chunk_id() -> None:
    # The chunk_id anchor is mandatory: dangling-citation defence (Req 4.3) is
    # only possible if every Citation actually carries the field to check.
    with pytest.raises(ValidationError):
        Citation.model_validate({"source": "doc", "locator": "page=3", "score": 0.9})


def test_score_must_be_numeric() -> None:
    with pytest.raises(ValidationError):
        RetrievedChunk.model_validate(
            {
                "chunk_id": "doc::0001",
                "source": "doc",
                "locator": "page=3",
                "text": "x",
                "score": "not-a-number",
            }
        )
