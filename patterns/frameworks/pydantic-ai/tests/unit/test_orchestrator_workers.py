"""Orchestrator-workers unit tests (Spec 005 Req 3 / 4.3)."""

from __future__ import annotations

import pytest

from patterns_pydantic_ai.orchestrator_workers import run_orchestrator
from tests.support.model_fakes import scripted_model


def _plan(*descriptions: str) -> dict[str, list[dict[str, str]]]:
    return {"subtasks": [{"description": d} for d in descriptions]}


async def test_orchestrator_runs_all_workers_in_plan_order() -> None:
    model = scripted_model(plan_payload=_plan("alpha", "beta"), text="worker-out")
    result = await run_orchestrator("compare alpha and beta", model=model)
    assert [r.subtask.description for r in result.results] == ["alpha", "beta"]
    assert all(r.output == "worker-out" for r in result.results)
    assert result.summary == "worker-out"
    assert result.truncated is False


async def test_orchestrator_caps_workers_and_flags_truncation() -> None:
    # Req 3.2: the planner emitted 4 subtasks but only max_workers run;
    # the full plan is preserved and the cap is discernible via `truncated`.
    model = scripted_model(plan_payload=_plan("a", "b", "c", "d"), text="out")
    result = await run_orchestrator("big task", model=model, max_workers=2)
    assert len(result.plan.subtasks) == 4
    assert [r.subtask.description for r in result.results] == ["a", "b"]
    assert result.truncated is True


async def test_orchestrator_rejects_non_positive_max_workers() -> None:
    model = scripted_model(plan_payload=_plan("a"), text="out")
    with pytest.raises(ValueError, match="max_workers"):
        await run_orchestrator("task", model=model, max_workers=0)
