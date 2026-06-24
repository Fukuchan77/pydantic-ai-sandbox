"""Fan-out cap guardrail tests for the Deep Research lane (Spec 009 Req 7, 4.1).

A plan with more subquestions than ``max_researchers`` must run exactly
``max_researchers`` sub-researchers (the orchestrator-workers ``max_workers``
mitigation: an unbounded plan must not become unbounded LLM calls), set
``ResearchReport.truncated``, and keep the findings in plan order. A plan within
the cap runs untruncated.
"""

from __future__ import annotations

import pytest

from patterns_deep_research import run_deep_research
from tests.support.fake_search import FakeSearchProvider
from tests.support.model_fakes import plan_payload, scripted_model

_FOUR = ["q1", "q2", "q3", "q4"]


async def test_plan_beyond_cap_is_truncated_and_ordered() -> None:
    model = scripted_model(plan=plan_payload(_FOUR))
    report = await run_deep_research(
        "q", model=model, search=FakeSearchProvider(), max_researchers=2
    )
    assert len(report.findings) == 2
    assert report.truncated is True
    # Findings stay in plan order (asyncio.gather preserves input order).
    assert [f.subquestion.description for f in report.findings] == ["q1", "q2"]


async def test_plan_within_cap_is_not_truncated() -> None:
    model = scripted_model(plan=plan_payload(["only-one"]))
    report = await run_deep_research(
        "q", model=model, search=FakeSearchProvider(), max_researchers=3
    )
    assert len(report.findings) == 1
    assert report.truncated is False


async def test_non_positive_caps_loud_fail() -> None:
    model = scripted_model(plan=plan_payload(["q"]))
    with pytest.raises(ValueError, match="max_researchers must be >= 1"):
        await run_deep_research("q", model=model, search=FakeSearchProvider(), max_researchers=0)
    with pytest.raises(ValueError, match="max_iterations must be >= 1"):
        await run_deep_research("q", model=model, search=FakeSearchProvider(), max_iterations=0)
    with pytest.raises(ValueError, match="top_k must be >= 1"):
        await run_deep_research("q", model=model, search=FakeSearchProvider(), top_k=0)
