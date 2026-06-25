"""Behavioral shape contract for the Deep Research models (Spec 009 Req 2.1).

Complements the AST/introspection parity in ``test_contract_drift.py`` by
exercising the Deep Research contracts at runtime: that they re-export from the
package root, expose exactly their declared fields, reuse ``Citation`` from the
RAG contract, and that the ``ProgressEvent`` discriminated union round-trips
through ``TypeAdapter``. Pipeline-level invariants (the >=1-citation grounding
rule, the fan-out/iteration caps) are deliberately *not* asserted here -- those
loud-fails live in the lane (``patterns_deep_research``), not the dependency-zero
contract.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from patterns_contracts import (
    BriefReadyEvent,
    Citation,
    Finding,
    FindingReadyEvent,
    PlanReadyEvent,
    ProgressEvent,
    ReportReadyEvent,
    ResearchBrief,
    ResearcherStartedEvent,
    ResearchNote,
    ResearchPlan,
    ResearchReport,
    SearchQuery,
    SearchResult,
    SubQuestion,
)

_MODELS = (
    ResearchBrief,
    SubQuestion,
    ResearchPlan,
    SearchQuery,
    SearchResult,
    ResearchNote,
    Finding,
    ResearchReport,
    BriefReadyEvent,
    PlanReadyEvent,
    ResearcherStartedEvent,
    FindingReadyEvent,
    ReportReadyEvent,
)


def test_deep_research_models_reexport_from_package_root() -> None:
    package = __import__("patterns_contracts")
    for model in _MODELS:
        assert issubclass(model, BaseModel)
        assert model.__name__ in package.__all__
    assert "ProgressEvent" in package.__all__


def test_field_sets() -> None:
    assert set(ResearchBrief.model_fields) == {"query", "objective", "out_of_scope"}
    assert set(SubQuestion.model_fields) == {"description"}
    assert set(ResearchPlan.model_fields) == {"brief", "subquestions"}
    assert set(SearchQuery.model_fields) == {"text"}
    assert set(SearchResult.model_fields) == {"source", "locator", "snippet", "score"}
    assert set(ResearchNote.model_fields) == {"source", "locator", "key_point", "score"}
    assert set(Finding.model_fields) == {
        "subquestion",
        "summary",
        "citations",
        "iterations",
        "truncated",
        "notes",
    }
    assert set(ResearchReport.model_fields) == {
        "brief",
        "findings",
        "report",
        "citations",
        "truncated",
    }


def test_event_field_sets() -> None:
    assert set(BriefReadyEvent.model_fields) == {"type", "objective"}
    assert set(PlanReadyEvent.model_fields) == {"type", "count"}
    assert set(ResearcherStartedEvent.model_fields) == {"type", "subquestion"}
    assert set(FindingReadyEvent.model_fields) == {"type", "subquestion", "citation_count"}
    assert set(ReportReadyEvent.model_fields) == {"type", "citation_count"}


def test_research_note_is_frozen() -> None:
    note = ResearchNote(source="doc", locator="url=a", key_point="X is a thing", score=0.9)
    with pytest.raises(ValidationError):
        note.score = 0.1  # frozen=True forbids mutation


def test_finding_notes_defaults_to_empty_list() -> None:
    finding = Finding.model_validate(
        {
            "subquestion": {"description": "What is X?"},
            "summary": "X is a thing.",
            "citations": [
                {"source": "doc", "locator": "url=a", "chunk_id": "doc::0001", "score": 0.9},
            ],
            "iterations": 2,
        }
    )
    # default=[] is deep-copied per instance by Pydantic v2, so backward compatible.
    assert finding.notes == []


def test_finding_carries_research_notes() -> None:
    finding = Finding.model_validate(
        {
            "subquestion": {"description": "What is X?"},
            "summary": "X is a thing.",
            "citations": [
                {"source": "doc", "locator": "url=a", "chunk_id": "doc::0001", "score": 0.9},
            ],
            "iterations": 2,
            "notes": [
                {"source": "doc", "locator": "url=a", "key_point": "X is a thing", "score": 0.9},
            ],
        }
    )
    assert isinstance(finding.notes[0], ResearchNote)
    assert finding.notes[0].key_point == "X is a thing"


def test_finding_reuses_citation_from_rag() -> None:
    finding = Finding.model_validate(
        {
            "subquestion": {"description": "What is X?"},
            "summary": "X is a thing.",
            "citations": [
                {"source": "doc", "locator": "url=a", "chunk_id": "doc::0001", "score": 0.9},
            ],
            "iterations": 2,
        }
    )
    assert isinstance(finding.citations[0], Citation)
    assert finding.citations[0].chunk_id == "doc::0001"
    assert finding.truncated is False  # defaults applied


def test_research_report_nests_findings_and_citations() -> None:
    report = ResearchReport.model_validate(
        {
            "brief": {"query": "q", "objective": "o", "out_of_scope": []},
            "findings": [],
            "report": "the report",
            "citations": [],
        }
    )
    assert report.truncated is False
    assert isinstance(report.brief, ResearchBrief)


def test_progress_event_discriminated_roundtrip() -> None:
    adapter: TypeAdapter[object] = TypeAdapter(ProgressEvent)
    for event in (
        BriefReadyEvent(objective="o"),
        PlanReadyEvent(count=3),
        ResearcherStartedEvent(subquestion="sq"),
        FindingReadyEvent(subquestion="sq", citation_count=2),
        ReportReadyEvent(citation_count=5),
    ):
        restored = adapter.validate_json(event.model_dump_json())
        assert restored == event


def test_search_result_score_must_be_numeric() -> None:
    with pytest.raises(ValidationError):
        SearchResult.model_validate(
            {"source": "s", "locator": "l", "snippet": "x", "score": "not-a-number"}
        )
