"""Reference-verification eval for the Deep Research lane (Spec 011 Req 2.3/2.4/4.2).

Proves the deep-research lane imports the *same* shared ``GradeReport`` / ``Judge``
contract from ``patterns_contracts`` and grades its own runtime result --
``ResearchReport``, including the spec-010 ``Finding.notes`` (Req 2.3) -- with a
deterministic fake judge, network I/O zero (Req 4.1, enforced by the autouse
``block_network`` guard).

The R2.4 discipline ("empty / low-signal ``key_point`` -> faithfulness
``Unknown``") is extracted into the pure helper ``faithfulness_rating_for`` and
exercised at both branches directly, so the mapping rule itself is tested rather
than baked into the fake's script; a separate end-to-end case proves the fake
judge surfaces that verdict on a low-signal ``ResearchReport``.

RED until Task 3.2 adds ``faithfulness_rating_for`` + the fake
``Judge[ResearchReport]`` to ``tests/support/model_fakes.py`` (import-error red,
the same intermediate shape established by Task 1.1).
"""

from __future__ import annotations

import pytest
from patterns_contracts import (
    Citation,
    Finding,
    GradeReport,
    Judge,
    Rating,
    ResearchBrief,
    ResearchNote,
    ResearchReport,
    SubQuestion,
)

from tests.support.model_fakes import FakeResearchReportJudge, faithfulness_rating_for


def _note(
    key_point: str, *, source: str = "anthropic-multi-agent", score: float = 0.9
) -> ResearchNote:
    """Build one distilled note carrying the given (possibly empty) key point."""
    return ResearchNote(source=source, locator="intro", key_point=key_point, score=score)


def _report(*, notes: list[ResearchNote]) -> ResearchReport:
    """Build a minimal grounded ``ResearchReport`` whose single finding carries ``notes``."""
    citation = Citation(source="anthropic-multi-agent", locator="intro", chunk_id="c1", score=0.9)
    finding = Finding(
        subquestion=SubQuestion(description="What are the trade-offs of multi-agent research?"),
        summary="A lead agent plans; bounded parallel sub-researchers gather and reflect.",
        citations=[citation],
        iterations=1,
        notes=notes,
    )
    return ResearchReport(
        brief=ResearchBrief(
            query="trade-offs of multi-agent research",
            objective="Cover the trade-offs of multi-agent research systems.",
            out_of_scope=[],
        ),
        findings=[finding],
        report="A synthesised report [anthropic-multi-agent#intro].",
        citations=[citation],
    )


@pytest.mark.parametrize("blank", ["", "   ", "\t", "\n  "])
def test_faithfulness_rating_for_low_signal_key_point_is_unknown(blank: str) -> None:
    # R2.4: an empty / low-signal key_point must map to evidence-deficient
    # "unknown", never a silent numeric score.
    rating: Rating = faithfulness_rating_for([_note(blank)])
    assert rating == "unknown"


def test_faithfulness_rating_for_empty_notes_is_unknown() -> None:
    # No distilled notes at all -> no evidence -> Unknown, not a default pass.
    assert faithfulness_rating_for([]) == "unknown"


def test_faithfulness_rating_for_grounded_key_point_is_numeric() -> None:
    # A non-empty, high-signal key_point yields a discrete numeric rating.
    rating: Rating = faithfulness_rating_for([_note("Lead plus parallel sub-researchers")])
    assert rating in {"1", "2", "3", "4", "5"}


def test_faithfulness_rating_for_partial_signal_is_below_full() -> None:
    # Mixed notebook (one grounded, one blank) -> partial credit, strictly below
    # the all-grounded score: pins the middle branch, not just the unknown/full
    # extremes, so a regression collapsing partial into full is caught.
    full: Rating = faithfulness_rating_for([_note("grounded point")])
    partial: Rating = faithfulness_rating_for([_note("grounded point"), _note("")])
    assert partial in {"1", "2", "3", "4", "5"}
    assert int(partial) < int(full)


async def test_fake_judge_grades_research_report_into_gradereport() -> None:
    # R2.3/4.2: the lane grades its own ResearchReport (notes included) into the
    # shared GradeReport, with outcome and behavior axes physically separated.
    report = _report(notes=[_note("Lead plus parallel sub-researchers")])

    graded = await FakeResearchReportJudge().grade(report)

    assert isinstance(graded, GradeReport)
    assert [axis.criterion for axis in graded.outcome_scores]  # outcome axis populated
    behavior_criteria = {axis.criterion for axis in graded.behavior_scores}
    assert "faithfulness" in behavior_criteria
    faithfulness = next(a for a in graded.behavior_scores if a.criterion == "faithfulness")
    assert faithfulness.rating in {"1", "2", "3", "4", "5"}  # grounded -> numeric
    assert graded.judge_id is not None  # provenance stamped (R3.3)


async def test_fake_judge_maps_low_signal_notes_to_unknown_faithfulness() -> None:
    # End-to-end R2.4: a report whose distilled notes are all empty key points
    # surfaces faithfulness="unknown" -- the fake calls faithfulness_rating_for
    # rather than baking the verdict into its script (no tautology).
    report = _report(notes=[_note(""), _note("   ")])

    graded = await FakeResearchReportJudge().grade(report)

    faithfulness = next(a for a in graded.behavior_scores if a.criterion == "faithfulness")
    assert faithfulness.rating == "unknown"


async def test_fake_judge_conforms_to_judge_protocol_seam() -> None:
    # Bind through the Protocol-typed seam so pyright verifies structural
    # conformance; await so the async grade() contract executes at runtime.
    async def run(judge: Judge[ResearchReport], subject: ResearchReport, /) -> GradeReport:
        return await judge.grade(subject)

    graded = await run(FakeResearchReportJudge(), _report(notes=[_note("grounded point")]))
    assert isinstance(graded, GradeReport)
