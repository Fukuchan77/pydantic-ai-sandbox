"""Pattern contracts shared across all three framework lanes (Spec 005 Req 2.1/3.1).

The normative copy of these models lives in ``patterns/routing/README.md``
and ``patterns/orchestrator-workers/README.md``; each lane carries an
identical duplicate (plan AD-3) so the independent uv projects never
import across lane boundaries (NFR-3). The cross-lane contract test
asserts the field-name sets stay in lockstep — edit all three lanes (and
the README normative copy) together.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

__all__ = [
    "OrchestratedResult",
    "Route",
    "RouteDecision",
    "RoutedAnswer",
    "SubTask",
    "TaskPlan",
    "WorkerResult",
]

Route = Literal["billing", "technical", "general"]
"""Closed routing vocabulary (Req 2.3): values outside this Literal fail
validation instead of silently falling back — an OWASP Agentic AI
excessive-agency mitigation (research.md R-7)."""


class RouteDecision(BaseModel):
    """Classifier output for the routing pattern."""

    route: Route = Field(description="Which specialist lane should answer the query.")
    reasoning: str = Field(description="One-sentence justification for the chosen route.")


class RoutedAnswer(BaseModel):
    """Final output of the routing pattern."""

    route: Route = Field(description="Route that produced the answer.")
    answer: str = Field(description="Specialist answer to the user query.")


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
