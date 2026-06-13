"""Orchestrator-workers pattern contracts (Spec 006-2a Req 1.3).

This module is the single source of truth for the orchestrator-workers pattern's
planner/worker/synthesizer Pydantic models; the normative copy also lives in
``patterns/orchestrator-workers/README.md`` fenced block, asserted equal by the
single-point drift test (Task 2.3). Ported unchanged from the per-lane
``contracts.py`` duplicates of Spec 005 (NFR-3).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = [
    "OrchestratedResult",
    "SubTask",
    "TaskPlan",
    "WorkerResult",
]


class SubTask(BaseModel):
    """A single planner-emitted unit of work for orchestrator-workers."""

    description: str = Field(description="Self-contained instruction for one worker.")


class TaskPlan(BaseModel):
    """Planner output for the orchestrator-workers pattern."""

    subtasks: list[SubTask] = Field(description="Ordered subtasks decomposing the user task.")


class WorkerResult(BaseModel):
    """One worker's completed output, paired with the subtask it served."""

    subtask: SubTask
    output: str = Field(description="Worker answer for the paired subtask.")


class OrchestratedResult(BaseModel):
    """Final output of the orchestrator-workers pattern.

    ``plan`` keeps the planner's *full* subtask list while ``results`` is
    capped at ``max_workers`` — together with ``truncated`` this makes any
    cap enforcement discernible from the result alone (Req 3.2).
    """

    plan: TaskPlan
    results: list[WorkerResult]
    summary: str = Field(description="Synthesizer's consolidated answer.")
    truncated: bool = Field(
        default=False,
        description="True when the planner emitted more subtasks than max_workers allowed.",
    )
