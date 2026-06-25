"""Structured note-taking + compaction tests (Anthropic context engineering).

Exercise the deterministic, model-free notebook helpers offline: snippet
distillation to a first-sentence key point, deduplication by source anchor
(highest score wins), score-ranked compaction to a bounded set, the rendered
notebook block, and the ``compact_digest`` drop-in for ``researcher._results_digest``.
"""

from __future__ import annotations

import pytest
from patterns_contracts import ResearchNote as ContractResearchNote
from patterns_contracts import SearchResult
from pydantic import ValidationError

from patterns_deep_research.notes import (
    ResearchNote,
    compact_digest,
    distill_notes,
    render_notebook,
)


def _result(source: str, locator: str, snippet: str, score: float) -> SearchResult:
    return SearchResult(source=source, locator=locator, snippet=snippet, score=score)


def test_distill_dedups_by_anchor_and_ranks_by_score() -> None:
    results = [
        _result("A", "1", "Alpha is first. More detail.", 0.9),
        _result("A", "1", "Alpha duplicate lower score.", 0.5),  # dup, lower -> ignored
        _result("B", "2", "Beta point. Extra.", 0.95),
        _result("C", "3", "Gamma point", 0.95),  # ties B at 0.95 -> source breaks tie
    ]
    notes = distill_notes(results)

    # One note per (source, locator); ordered by -score then (source, locator).
    assert [(note.source, note.locator) for note in notes] == [("B", "2"), ("C", "3"), ("A", "1")]
    # The retained A note is the higher-scoring duplicate, distilled to its lead sentence.
    assert notes[0].key_point == "Beta point"
    assert notes[2] == ResearchNote(source="A", locator="1", key_point="Alpha is first", score=0.9)


def test_distill_replaces_a_lower_scoring_duplicate_with_a_higher_one() -> None:
    results = [
        _result("A", "1", "First seen, lower.", 0.4),
        _result("A", "1", "Later, higher score wins.", 0.8),
    ]
    notes = distill_notes(results)
    assert len(notes) == 1
    assert notes[0].score == 0.8


def test_distill_compacts_to_the_top_max_notes() -> None:
    results = [_result(f"S{index}", "1", f"Point {index}", float(index)) for index in range(6)]
    notes = distill_notes(results, max_notes=2)
    # Compaction budget keeps only the two highest-scoring notes.
    assert [note.score for note in notes] == [5.0, 4.0]


def test_key_point_strips_trailing_period_and_truncates_long_text() -> None:
    # A single sentence ending in a period keeps no trailing punctuation.
    short = distill_notes([_result("A", "1", "Single sentence.", 1.0)])[0]
    assert short.key_point == "Single sentence"

    # An over-long key point is truncated to the cap and marked.
    long_point = distill_notes([_result("A", "1", "x" * 200, 1.0)], key_point_chars=20)[0].key_point
    assert long_point.endswith("…")
    assert len(long_point) == 21  # 20-char cap + 1-char marker


def test_distill_rejects_non_positive_bounds() -> None:
    with pytest.raises(ValueError, match="max_notes must be"):
        distill_notes([], max_notes=0)
    with pytest.raises(ValueError, match="key_point_chars must be"):
        distill_notes([], key_point_chars=0)


def test_render_notebook_handles_empty_and_populated_notebooks() -> None:
    assert render_notebook([]) == "(no notes yet)"
    rendered = render_notebook(
        [ResearchNote(source="A", locator="1", key_point="key thing", score=0.9)]
    )
    assert rendered == "- [A#1] key thing"


def test_compact_digest_is_a_bounded_drop_in_for_results_digest() -> None:
    results = [
        _result(f"S{index}", "1", f"Finding {index}. detail.", float(index)) for index in range(8)
    ]
    digest = compact_digest(results, max_notes=3)
    lines = digest.splitlines()
    # Bounded to the compaction budget, highest-signal first, one line per note.
    assert len(lines) == 3
    assert lines[0] == "- [S7#1] Finding 7"
    # Empty input renders the placeholder, matching the lane's digest idiom.
    assert compact_digest([]) == "(no notes yet)"


def test_research_note_is_the_promoted_contract_single_entity() -> None:
    # notes.ResearchNote must BE the promoted patterns_contracts.ResearchNote,
    # not a local redefinition — identical object identity proves a single
    # entity. RED until notes.py migrates its import (Task 2.2).
    assert id(ResearchNote) == id(ContractResearchNote)


def test_research_note_is_a_frozen_basemodel() -> None:
    note = ResearchNote(source="A", locator="1", key_point="key thing", score=0.9)
    # Post-migration frozen immutability follows pydantic: mutation raises
    # ValidationError (the local frozen dataclass raised FrozenInstanceError).
    # The attribute name is held in a variable so the staged migration keeps the
    # lint/type gates green; the runtime frozen rejection is the assertion.
    frozen_field = "score"
    with pytest.raises(ValidationError):
        setattr(note, frozen_field, 0.1)


def test_research_note_keyword_construction_and_value_equality() -> None:
    # Keyword construction and field-wise value equality are preserved across
    # the dataclass -> BaseModel migration.
    one = ResearchNote(source="A", locator="1", key_point="key thing", score=0.9)
    same = ResearchNote(source="A", locator="1", key_point="key thing", score=0.9)
    other = ResearchNote(source="A", locator="1", key_point="key thing", score=0.1)
    assert one == same
    assert one != other


def test_distill_notes_returns_empty_for_empty_input() -> None:
    # No gathered results -> empty notebook (Finding.notes stays [] for the handoff).
    assert distill_notes([]) == []
