"""Orchestrator-workers pattern — PydanticAI implementation (Spec 005 Req 3).

Three-stage flow (Anthropic "Building Effective Agents"):

1. **Planner** agent (``output_type=TaskPlan``) decomposes the task into
   subtasks dynamically — the LLM, not the code, decides the breakdown.
2. **Workers** run in parallel via ``asyncio.gather``; the subtask list is
   capped at ``max_workers`` first (Req 3.2 — an unbounded plan must not
   translate into unbounded LLM calls; OWASP Agentic AI excessive-agency /
   unbounded-consumption mitigation, research.md R-7).
3. **Synthesizer** agent merges worker outputs into one summary.

Result ordering follows the plan's subtask order because ``asyncio.gather``
preserves input order (Req 3.3).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from patterns_contracts import OrchestratedResult, TaskPlan, WorkerResult
from pydantic_ai import Agent
from pydantic_ai.models.instrumented import instrument_model

if TYPE_CHECKING:
    from pydantic_ai.models import Model
    from pydantic_ai.models.instrumented import InstrumentationSettings

__all__ = ["run_orchestrator"]


_PLANNER_INSTRUCTIONS = (
    "You are a planning orchestrator. Decompose the user's task into a "
    "small list of self-contained subtasks (typically 2-3). Each subtask "
    "description must be answerable on its own, without seeing the other "
    "subtasks."
)

_WORKER_INSTRUCTIONS = (
    "You are a focused worker. Complete exactly the subtask you are given, "
    "concisely. Do not attempt the wider task."
)

_SYNTHESIZER_INSTRUCTIONS = (
    "You are a synthesizer. Merge the worker outputs you are given into "
    "one coherent answer to the original task."
)


def _agent(model: Model, instructions: str) -> Agent[None, str]:
    """Construct a plain-text agent with shared settings."""
    return Agent[None, str](
        model=model,
        output_type=str,
        instructions=instructions,
        deps_type=type(None),
    )


async def run_orchestrator(
    task: str,
    *,
    model: Model,
    max_workers: int = 3,
    instrumentation: InstrumentationSettings | None = None,
) -> OrchestratedResult:
    """Plan ``task``, fan out workers in parallel, and synthesize a summary.

    Args:
        task: The user task to decompose and solve.
        model: PydanticAI model powering all three stages (DI seam shared
            with :func:`patterns_pydantic_ai.routing.run_routing`).
        max_workers: Hard cap on parallel workers. Planner output beyond
            the cap is dropped and flagged via ``truncated`` (Req 3.2).
        instrumentation: Optional ``InstrumentationSettings``; when set
            the model is wrapped via ``instrument_model`` (V2 API). ``None``
            keeps the run uninstrumented.

    Returns:
        The contract-level :class:`OrchestratedResult` whose ``plan``
        retains the *full* planner output while ``results`` holds at most
        ``max_workers`` entries, in plan order.

    Raises:
        ValueError: If ``max_workers`` is not positive — a zero/negative
            cap would silently produce an empty run.
    """
    if max_workers < 1:
        msg = f"max_workers must be >= 1, got {max_workers}"
        raise ValueError(msg)

    resolved = instrument_model(model, instrumentation) if instrumentation else model
    planner = Agent[None, TaskPlan](
        model=resolved,
        output_type=TaskPlan,
        instructions=_PLANNER_INSTRUCTIONS,
        deps_type=type(None),
    )
    plan = (await planner.run(task)).output

    selected = plan.subtasks[:max_workers]
    worker = _agent(resolved, _WORKER_INSTRUCTIONS)
    worker_runs = await asyncio.gather(
        *(
            worker.run(f"Original task: {task}\n\nYour subtask: {subtask.description}")
            for subtask in selected
        )
    )
    results = [
        WorkerResult(subtask=subtask, output=run.output)
        for subtask, run in zip(selected, worker_runs, strict=True)
    ]

    synthesizer = _agent(resolved, _SYNTHESIZER_INSTRUCTIONS)
    worker_digest = "\n\n".join(
        f"Subtask: {result.subtask.description}\nOutput: {result.output}" for result in results
    )
    summary = (
        await synthesizer.run(f"Original task: {task}\n\nWorker outputs:\n{worker_digest}")
    ).output

    return OrchestratedResult(
        plan=plan,
        results=results,
        summary=summary,
        truncated=len(plan.subtasks) > max_workers,
    )
