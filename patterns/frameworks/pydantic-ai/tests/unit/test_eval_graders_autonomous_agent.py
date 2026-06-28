"""Reference-verification eval for the autonomous-agent pattern (Spec 011 Req 2.1/4.2).

Proves the pydantic-ai lane imports the *same* shared ``GradeReport`` / ``Judge``
contract from ``patterns_contracts`` and grades its own runtime result --
``AgentRunResult`` -- with a deterministic fake judge, network I/O zero (Req 4.1,
enforced lane-wide by ``conftest`` flipping ``ALLOW_MODEL_REQUESTS`` off). The
autonomous-agent's process discipline maps onto the *behavior* axis: the fake
scores ``tool_use_discipline`` (did the loop stay within ``allowed_tools``) and
``guardrail_adherence`` (did it respect approval / budget / iteration caps),
distinct from the *outcome* axis that scores the final answer.

RED until Task 4.2 adds the fake ``Judge[AgentRunResult]`` to
``tests/support/model_fakes.py`` (import-error red, the same intermediate shape
established by deep-research Task 3.1).
"""

from __future__ import annotations

from patterns_contracts import AgentRunResult, AgentStep, GradeReport, Judge

from tests.support.model_fakes import FakeAgentRunResultJudge


def _result() -> AgentRunResult:
    """Build a minimal completed ``AgentRunResult`` for grading."""
    return AgentRunResult(
        steps=[
            AgentStep(index=0, tool="search", observation="found three sources", budget_spent=8),
            AgentStep(index=1, tool="read", observation="extracted the key claim", budget_spent=6),
        ],
        final_output="The synthesised answer.",
        stop_reason="completed",
        total_budget_spent=14,
    )


async def test_fake_judge_grades_agent_run_result_into_gradereport() -> None:
    # R2.1/4.2: the lane grades its own AgentRunResult into the shared
    # GradeReport, with outcome and behavior axes physically separated (Req 1.2).
    result = _result()

    graded = await FakeAgentRunResultJudge().grade(result)

    assert isinstance(graded, GradeReport)
    assert [axis.criterion for axis in graded.outcome_scores]  # outcome axis populated
    assert isinstance(graded.aggregate, float)  # partial-credit aggregate (Req 1.3)
    assert graded.judge_id is not None  # provenance stamped (R3.3)


async def test_fake_judge_behavior_axis_scores_process_discipline() -> None:
    # The autonomous-agent's guardrails are *behavior*, not outcome: the fake
    # must score tool_use_discipline and guardrail_adherence on the behavior axis.
    graded = await FakeAgentRunResultJudge().grade(_result())

    behavior_criteria = {axis.criterion for axis in graded.behavior_scores}
    assert "tool_use_discipline" in behavior_criteria
    assert "guardrail_adherence" in behavior_criteria
    for axis in graded.behavior_scores:
        assert axis.rating in {"1", "2", "3", "4", "5", "unknown"}


async def test_fake_judge_conforms_to_judge_protocol_seam() -> None:
    # Bind through the Protocol-typed seam so pyright verifies structural
    # conformance; await so the async grade() contract executes at runtime.
    async def run(judge: Judge[AgentRunResult], subject: AgentRunResult, /) -> GradeReport:
        return await judge.grade(subject)

    graded = await run(FakeAgentRunResultJudge(), _result())
    assert isinstance(graded, GradeReport)
