"""Orchestrator-workers unit tests (Spec 005 Req 3 / 4.3)."""

from __future__ import annotations

import pytest

from patterns_llamaindex.orchestrator_workers import run_orchestrator
from tests.support.fake_llm import ScriptedLLM


def _plan(*descriptions: str) -> dict[str, list[dict[str, str]]]:
    return {"subtasks": [{"description": d} for d in descriptions]}


async def test_orchestrator_runs_all_workers_in_plan_order() -> None:
    llm = ScriptedLLM(plan_payload=_plan("alpha", "beta"), text="worker-out")
    result = await run_orchestrator("compare alpha and beta", llm=llm)
    # Req 3.3: result order follows plan order even though the fan-in
    # collects events in nondeterministic arrival order.
    assert [r.subtask.description for r in result.results] == ["alpha", "beta"]
    assert all(r.output == "worker-out" for r in result.results)
    assert result.summary == "worker-out"
    assert result.truncated is False


async def test_orchestrator_caps_workers_and_flags_truncation() -> None:
    llm = ScriptedLLM(plan_payload=_plan("a", "b", "c", "d"), text="out")
    result = await run_orchestrator("big task", llm=llm, max_workers=2)
    assert len(result.plan.subtasks) == 4
    assert [r.subtask.description for r in result.results] == ["a", "b"]
    assert result.truncated is True


async def test_orchestrator_rejects_non_positive_max_workers() -> None:
    llm = ScriptedLLM(plan_payload=_plan("a"), text="out")
    with pytest.raises(ValueError, match="max_workers"):
        await run_orchestrator("task", llm=llm, max_workers=0)
