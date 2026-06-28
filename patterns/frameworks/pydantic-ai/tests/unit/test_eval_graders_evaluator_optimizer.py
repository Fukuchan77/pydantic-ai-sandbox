"""Reference-verification eval for the evaluator-optimizer pattern (Spec 011 Req 2.1/4.2).

Proves the pydantic-ai lane imports the *same* shared ``GradeReport`` / ``Judge``
contract from ``patterns_contracts`` and grades its own runtime result --
``OptimizationResult`` -- with a deterministic fake judge, network I/O zero
(Req 4.1, enforced lane-wide by ``conftest`` flipping ``ALLOW_MODEL_REQUESTS``
off). This is the offline/CI grader layer that *coexists* with the runtime
convergence gate (``stop_reason``), per ADR-4: it does not replace it.

RED until Task 4.2 adds the fake ``Judge[OptimizationResult]`` to
``tests/support/model_fakes.py`` (import-error red, the same intermediate shape
established by deep-research Task 3.1).
"""

from __future__ import annotations

from patterns_contracts import GradeReport, Iteration, Judge, OptimizationResult

from tests.support.model_fakes import FakeOptimizationResultJudge


def _result() -> OptimizationResult:
    """Build a minimal converged ``OptimizationResult`` for grading."""
    return OptimizationResult(
        iterations=[
            Iteration(
                index=0,
                candidate="A first draft answer.",
                verdict="revise",
                feedback="Tighten the claim and cite a source.",
            ),
            Iteration(
                index=1,
                candidate="A tightened, source-backed answer.",
                verdict="pass",
                feedback="",
            ),
        ],
        final_output="A tightened, source-backed answer.",
        stop_reason="passed",
    )


async def test_fake_judge_grades_optimization_result_into_gradereport() -> None:
    # R2.1/4.2: the lane grades its own OptimizationResult into the shared
    # GradeReport, with outcome and behavior axes physically separated (Req 1.2).
    result = _result()

    graded = await FakeOptimizationResultJudge().grade(result)

    assert isinstance(graded, GradeReport)
    assert [axis.criterion for axis in graded.outcome_scores]  # outcome axis populated
    assert [axis.criterion for axis in graded.behavior_scores]  # behavior axis populated
    assert isinstance(graded.aggregate, float)  # partial-credit aggregate (Req 1.3)
    assert graded.judge_id is not None  # provenance stamped (R3.3)


async def test_fake_judge_outcome_axis_scores_the_final_artifact() -> None:
    # outcome grader = final-artifact quality (Glossary): correctness must be
    # one of the scored outcome criteria, with a discrete rating.
    graded = await FakeOptimizationResultJudge().grade(_result())

    outcome_criteria = {axis.criterion for axis in graded.outcome_scores}
    assert "correctness" in outcome_criteria
    correctness = next(a for a in graded.outcome_scores if a.criterion == "correctness")
    assert correctness.rating in {"1", "2", "3", "4", "5", "unknown"}


async def test_fake_judge_conforms_to_judge_protocol_seam() -> None:
    # Bind through the Protocol-typed seam so pyright verifies structural
    # conformance; await so the async grade() contract executes at runtime.
    async def run(judge: Judge[OptimizationResult], subject: OptimizationResult, /) -> GradeReport:
        return await judge.grade(subject)

    graded = await run(FakeOptimizationResultJudge(), _result())
    assert isinstance(graded, GradeReport)
