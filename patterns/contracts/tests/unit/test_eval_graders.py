"""Behavioral shape contract for the shared eval-graders models (Spec 011 Req 1.x/3.x/4.1).

Exercises the outcome+behavior multi-axis grader contract at runtime: the
``Rating`` vocabulary (``"1"`` to ``"5"`` plus ``"unknown"``), the physical
outcome/behavior axis separation on ``GradeReport``, the partial-credit
``aggregate: float`` aggregation, the loud-fail ``rationale`` validator
(empty/whitespace construction is rejected), the optional ``judge_id`` provenance
metadata, and structural conformance to the injected ``Judge[SubjectT]`` Protocol
seam via an inline deterministic fake (network I/O zero -- Req 4.1).

These assertions deliberately target the dependency-zero contract surface only;
lane-side reference verification (R4.2) and the rubric prose (R1.4) live
elsewhere (the lane ``tests/support/`` fakes and ``patterns/EVAL-GRADERS.md``).
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from patterns_contracts import AxisScore, GradeReport, Judge, Rating


def test_grader_models_reexport_from_package_root() -> None:
    package = __import__("patterns_contracts")
    for name in ("AxisScore", "GradeReport", "Judge", "Rating"):
        assert name in package.__all__
    assert issubclass(AxisScore, BaseModel)
    assert issubclass(GradeReport, BaseModel)


def test_field_sets() -> None:
    assert set(AxisScore.model_fields) == {"criterion", "rating", "rationale"}
    assert set(GradeReport.model_fields) == {
        "outcome_scores",
        "behavior_scores",
        "aggregate",
        "judge_id",
    }


@pytest.mark.parametrize("rating", ["1", "2", "3", "4", "5", "unknown"])
def test_rating_vocabulary_is_accepted(rating: Rating) -> None:
    axis = AxisScore(criterion="correctness", rating=rating, rationale="grounded enough")
    assert axis.rating == rating


def test_rating_rejects_out_of_vocabulary_value() -> None:
    with pytest.raises(ValidationError):
        AxisScore(criterion="correctness", rating="6", rationale="r")  # type: ignore[arg-type]


@pytest.mark.parametrize("blank", ["", "   ", "\t", "\n  "])
def test_empty_or_whitespace_rationale_is_loud_fail(blank: str) -> None:
    with pytest.raises(ValidationError):
        AxisScore(criterion="correctness", rating="3", rationale=blank)


def test_outcome_and_behavior_axes_are_separated_with_partial_credit() -> None:
    # Outcome carries an evidence-deficient "unknown"; behavior mixes numeric
    # ratings -- the report must still build and accept a float partial-credit
    # aggregate (R1.2 axis separation + R1.3 partial credit).
    report = GradeReport(
        outcome_scores=[
            AxisScore(criterion="correctness", rating="4", rationale="mostly right"),
            AxisScore(criterion="completeness", rating="unknown", rationale="no evidence"),
        ],
        behavior_scores=[
            AxisScore(criterion="tool_use_discipline", rating="5", rationale="clean tool calls"),
            AxisScore(criterion="guardrail_adherence", rating="3", rationale="one slip"),
        ],
        aggregate=0.75,
    )
    assert [a.criterion for a in report.outcome_scores] == ["correctness", "completeness"]
    assert [a.criterion for a in report.behavior_scores] == [
        "tool_use_discipline",
        "guardrail_adherence",
    ]
    assert report.outcome_scores[1].rating == "unknown"
    assert isinstance(report.aggregate, float)
    assert report.aggregate == 0.75


def test_judge_id_is_optional_and_defaults_to_none() -> None:
    report = GradeReport(outcome_scores=[], behavior_scores=[], aggregate=0.0)
    assert report.judge_id is None
    stamped = GradeReport(
        outcome_scores=[],
        behavior_scores=[],
        aggregate=0.0,
        judge_id="independent-judge-v1",
    )
    assert stamped.judge_id == "independent-judge-v1"


async def test_judge_protocol_conformance_via_inline_fake() -> None:
    class _FakeJudge:
        """Inline deterministic Judge[str]; never touches the network (R3.2/4.1)."""

        async def grade(self, subject: str, /) -> GradeReport:
            return GradeReport(
                outcome_scores=[
                    AxisScore(criterion="correctness", rating="4", rationale=f"judged {subject!r}"),
                ],
                behavior_scores=[
                    AxisScore(criterion="faithfulness", rating="unknown", rationale="low signal"),
                ],
                aggregate=0.8,
                judge_id="fake",
            )

    # Bind through the Protocol-typed seam so pyright verifies structural
    # conformance; await it so the async grade() contract executes at runtime.
    async def run(judge: Judge[str], subject: str, /) -> GradeReport:
        return await judge.grade(subject)

    report = await run(_FakeJudge(), "candidate")
    assert isinstance(report, GradeReport)
    assert report.judge_id == "fake"
    assert report.outcome_scores[0].rating == "4"
    assert report.behavior_scores[0].rating == "unknown"


def test_rating_alias_is_exported() -> None:
    # Rating is a typing alias (Literal), not a class -- assert it is importable
    # and usable as an annotation source rather than asserting on its runtime kind.
    annotation: Rating = "unknown"
    assert annotation == "unknown"
