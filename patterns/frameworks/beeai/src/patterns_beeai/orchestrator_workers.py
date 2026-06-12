"""Orchestrator-workers pattern — BeeAI Framework implementation (Spec 005 Req 3).

State-machine flow::

    plan --(cap at max_workers)--> work --(asyncio.gather)--> synthesize --> END

BeeAI Workflows steps run sequentially by design (the state machine has a
single cursor), so worker parallelism lives *inside* the ``work`` step via
``asyncio.gather`` — the same fan-out primitive the PydanticAI lane uses,
wrapped in BeeAI's step/transition skeleton. Result order follows the
plan's subtask order because ``gather`` preserves input order (Req 3.3).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from beeai_framework.backend.message import SystemMessage, UserMessage
from beeai_framework.workflows.workflow import Workflow
from pydantic import BaseModel

from patterns_beeai.contracts import OrchestratedResult, TaskPlan, WorkerResult

if TYPE_CHECKING:
    from beeai_framework.backend.chat import ChatModel

__all__ = ["run_orchestrator"]


_PLAN_PROMPT = (
    "You are a planning orchestrator. Decompose the user's task into a "
    "small list of self-contained subtasks (typically 2-3). Each subtask "
    "description must be answerable on its own.\n\nTask: {task}"
)

_WORKER_SYSTEM = (
    "You are a focused worker. Complete exactly the subtask you are given, "
    "concisely. Do not attempt the wider task."
)

_SYNTHESIZER_SYSTEM = (
    "You are a synthesizer. Merge the worker outputs you are given into "
    "one coherent answer to the original task."
)


class _OrchestratorState(BaseModel):
    """Shared workflow state across plan/work/synthesize steps."""

    task: str
    max_workers: int
    plan: TaskPlan | None = None
    results: list[WorkerResult] = []
    summary: str | None = None


def _build_workflow(llm: ChatModel) -> Workflow[_OrchestratorState, str]:
    """Assemble the three-step orchestrator workflow over ``llm``."""
    workflow: Workflow[_OrchestratorState, str] = Workflow(
        schema=_OrchestratorState, name="orchestrator-workers"
    )

    async def plan(state: _OrchestratorState) -> str:
        output = await llm.create_structure(
            schema=TaskPlan,
            messages=[UserMessage(_PLAN_PROMPT.format(task=state.task))],
        )
        state.plan = TaskPlan.model_validate(output.object)
        return "work"

    async def work(state: _OrchestratorState) -> str:
        assert state.plan is not None  # set by plan
        selected = state.plan.subtasks[: state.max_workers]

        async def _run_worker(description: str) -> str:
            output = await llm.create(
                messages=[
                    SystemMessage(_WORKER_SYSTEM),
                    UserMessage(f"Original task: {state.task}\n\nYour subtask: {description}"),
                ]
            )
            return output.get_text_content()

        outputs = await asyncio.gather(*(_run_worker(subtask.description) for subtask in selected))
        state.results = [
            WorkerResult(subtask=subtask, output=output)
            for subtask, output in zip(selected, outputs, strict=True)
        ]
        return "synthesize"

    async def synthesize(state: _OrchestratorState) -> str:
        digest = "\n\n".join(
            f"Subtask: {result.subtask.description}\nOutput: {result.output}"
            for result in state.results
        )
        output = await llm.create(
            messages=[
                SystemMessage(_SYNTHESIZER_SYSTEM),
                UserMessage(f"Original task: {state.task}\n\nWorker outputs:\n{digest}"),
            ]
        )
        state.summary = output.get_text_content()
        return Workflow.END

    workflow.add_step("plan", plan)
    workflow.add_step("work", work)
    workflow.add_step("synthesize", synthesize)
    return workflow


async def run_orchestrator(
    task: str,
    *,
    llm: ChatModel,
    max_workers: int = 3,
) -> OrchestratedResult:
    """Plan ``task``, fan out workers, and synthesize a summary.

    Args:
        task: The user task to decompose and solve.
        llm: BeeAI ``ChatModel`` (fake in unit tests, Ollama in integration).
        max_workers: Hard cap on parallel workers (Req 3.2); planner output
            beyond the cap is dropped and flagged via ``truncated``.

    Returns:
        The contract-level :class:`OrchestratedResult` whose ``plan``
        retains the full planner output.

    Raises:
        ValueError: If ``max_workers`` is not positive.
    """
    if max_workers < 1:
        msg = f"max_workers must be >= 1, got {max_workers}"
        raise ValueError(msg)

    run = await _build_workflow(llm).run(_OrchestratorState(task=task, max_workers=max_workers))
    state = run.state
    assert state.plan is not None and state.summary is not None
    return OrchestratedResult(
        plan=state.plan,
        results=state.results,
        summary=state.summary,
        truncated=len(state.plan.subtasks) > max_workers,
    )
