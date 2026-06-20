"""Lead-agent brief/plan tests for the Deep Research lane (Spec 009 Req 3).

The lead agent must produce a ``ResearchPlan`` carrying a scoped ``ResearchBrief``
(objective + out_of_scope) and self-contained subquestions; the optional clarify
pre-step sharpens the query before planning without changing the plan's shape.
"""

from __future__ import annotations

from patterns_contracts import ResearchBrief, ResearchPlan

from patterns_deep_research.orchestrator import build_brief_and_plan
from tests.support.model_fakes import plan_payload, scripted_model


async def test_planner_returns_brief_and_subquestions() -> None:
    model = scripted_model(
        plan=plan_payload(
            ["What is the orchestrator role?", "How do sub-researchers run in parallel?"],
            objective="Explain multi-agent research orchestration.",
            out_of_scope=["single-agent RAG"],
        )
    )

    plan = await build_brief_and_plan("multi-agent research", model=model)

    assert isinstance(plan, ResearchPlan)
    assert isinstance(plan.brief, ResearchBrief)
    assert plan.brief.objective == "Explain multi-agent research orchestration."
    assert plan.brief.out_of_scope == ["single-agent RAG"]
    assert [sq.description for sq in plan.subquestions] == [
        "What is the orchestrator role?",
        "How do sub-researchers run in parallel?",
    ]


async def test_clarify_runs_an_extra_turn_without_changing_plan_shape() -> None:
    # With clarify on, a text turn (the clarifier) precedes the plan turn; the
    # scripted model serves the clarifier text then the plan by schema dispatch.
    model = scripted_model(
        plan=plan_payload(["sharpened subquestion"]),
        text="A sharpened, specific research question.",
    )

    plan = await build_brief_and_plan("vague query", model=model, clarify=True)

    assert [sq.description for sq in plan.subquestions] == ["sharpened subquestion"]
