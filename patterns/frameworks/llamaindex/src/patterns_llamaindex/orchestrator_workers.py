"""Orchestrator-workers pattern — LlamaIndex Workflows implementation (Spec 005 Req 3).

Event-driven fan-out/fan-in:

1. ``plan`` step: ``astructured_predict`` produces a :class:`TaskPlan`;
   the subtask list is capped at ``max_workers`` (Req 3.2) and one
   ``_WorkerEvent`` per surviving subtask is published via
   ``ctx.send_event`` — LlamaIndex's native fan-out.
2. ``work`` step (``num_workers``-parallel): each event is answered
   independently.
3. ``synthesize`` step: ``ctx.collect_events`` buffers results until all
   workers reported (fan-in), restores plan order by index (Req 3.3 —
   event arrival order is nondeterministic), and emits the summary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from llama_index.core.prompts import PromptTemplate

# `step` lacks complete stubs upstream; ignore is scoped to that name.
from llama_index.core.workflow import (
    Context,
    Event,
    StartEvent,
    StopEvent,
    Workflow,
    step,  # pyright: ignore[reportUnknownVariableType]
)
from patterns_contracts import OrchestratedResult, TaskPlan, WorkerResult

if TYPE_CHECKING:
    from llama_index.core.llms import LLM

__all__ = ["OrchestratorWorkflow", "run_orchestrator"]


_PLAN_TEMPLATE = PromptTemplate(
    "You are a planning orchestrator. Decompose the user's task into a "
    "small list of self-contained subtasks (typically 2-3). Each subtask "
    "description must be answerable on its own.\n\nTask: {task}"
)

_MAX_PARALLEL_WORKERS = 8
"""Static parallelism of the ``work`` step (set at decoration time by the
framework). The *effective* cap is the runtime ``max_workers`` argument,
enforced in ``plan`` by emitting at most that many worker events."""


class _WorkerEvent(Event):
    """Fan-out unit: one subtask for one worker."""

    index: int
    description: str
    task: str


class _ResultEvent(Event):
    """Fan-in unit: one worker's completed output."""

    index: int
    description: str
    output: str


class OrchestratorWorkflow(Workflow):
    """Plan → parallel workers → synthesize, over a caller-supplied ``LLM``."""

    def __init__(self, llm: LLM, max_workers: int = 3, **kwargs: object) -> None:
        """Validate the cap and store run configuration.

        Raises:
            ValueError: If ``max_workers`` is not positive.
        """
        if max_workers < 1:
            msg = f"max_workers must be >= 1, got {max_workers}"
            raise ValueError(msg)
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._llm = llm
        self._max_workers = max_workers

    @step
    async def plan(self, ev: StartEvent, ctx: Context) -> _WorkerEvent | None:
        """Stage 1: structured plan, cap enforcement, worker fan-out."""
        task = str(ev.get("task"))
        plan = await self._llm.astructured_predict(TaskPlan, _PLAN_TEMPLATE, task=task)
        selected = plan.subtasks[: self._max_workers]
        await ctx.store.set("plan", plan)
        await ctx.store.set("task", task)
        await ctx.store.set("num_workers", len(selected))
        for index, subtask in enumerate(selected):
            ctx.send_event(_WorkerEvent(index=index, description=subtask.description, task=task))
        return None

    @step(num_workers=_MAX_PARALLEL_WORKERS)  # pyright: ignore[reportUntypedFunctionDecorator]  # upstream stubs
    async def work(self, ev: _WorkerEvent) -> _ResultEvent:
        """Stage 2: answer one subtask (runs in parallel across events)."""
        response = await self._llm.acomplete(
            f"You are a focused worker. Complete exactly the subtask you are "
            f"given, concisely.\n\nOriginal task: {ev.task}\n\nYour subtask: {ev.description}"
        )
        return _ResultEvent(index=ev.index, description=ev.description, output=str(response))

    @step
    async def synthesize(self, ev: _ResultEvent, ctx: Context) -> StopEvent | None:
        """Stage 3: fan-in, order restoration, summary synthesis."""
        num_workers = cast("int", await ctx.store.get("num_workers"))
        collected = ctx.collect_events(ev, [_ResultEvent] * num_workers)
        if collected is None:
            return None

        results_by_index = sorted(
            (cast("_ResultEvent", event) for event in collected), key=lambda event: event.index
        )
        plan = cast("TaskPlan", await ctx.store.get("plan"))
        task = cast("str", await ctx.store.get("task"))
        results = [
            WorkerResult(subtask=plan.subtasks[event.index], output=event.output)
            for event in results_by_index
        ]
        digest = "\n\n".join(
            f"Subtask: {result.subtask.description}\nOutput: {result.output}" for result in results
        )
        summary = await self._llm.acomplete(
            f"You are a synthesizer. Merge the worker outputs into one coherent "
            f"answer to the original task.\n\nOriginal task: {task}\n\nWorker outputs:\n{digest}"
        )
        return StopEvent(
            result=OrchestratedResult(
                plan=plan,
                results=results,
                summary=str(summary),
                truncated=len(plan.subtasks) > num_workers,
            )
        )


async def run_orchestrator(
    task: str,
    *,
    llm: LLM,
    max_workers: int = 3,
    timeout: float = 240.0,
) -> OrchestratedResult:
    """Plan ``task``, fan out workers, and synthesize a summary.

    Args:
        task: The user task to decompose and solve.
        llm: LlamaIndex LLM (fake in unit tests, Ollama in integration).
        max_workers: Hard cap on worker events (Req 3.2).
        timeout: Workflow timeout in seconds.

    Returns:
        The contract-level :class:`OrchestratedResult`.

    Raises:
        ValueError: If ``max_workers`` is not positive.
    """
    workflow = OrchestratorWorkflow(llm=llm, max_workers=max_workers, timeout=timeout)
    # Same upstream-stub narrowing pattern as routing.run_routing.
    result = await workflow.run(task=task)  # pyright: ignore[reportUnknownVariableType]
    assert isinstance(result, OrchestratedResult)
    return result
