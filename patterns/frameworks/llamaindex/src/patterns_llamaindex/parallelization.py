"""Parallelization pattern — LlamaIndex Workflows implementation (Spec 006-2a Req 4).

Parallel fan-out over a single contract with two variants selected by the
``variant`` Literal (Anthropic "Building Effective Agents"):

* **sectioning** (Req 4.2) — ``n`` workers run concurrently and their outputs are
  merged into ``aggregate``. The contract carries a single ``task`` with no seam
  for caller-supplied subtasks, so every branch receives the *same* prompt and
  the split into "distinct portions" is delegated to the model via the worker
  instructions rather than performed here. Offline tests fabricate distinct
  per-branch outputs through the fake; a real model is not guaranteed to produce
  non-overlapping sections.
* **voting** (Req 4.3) — the *same* task fans out ``n`` ways; ``aggregate`` is
  the majority output, with ties broken deterministically toward the lowest
  branch ``index``.

The fan-out is the LlamaIndex-native worker-pool mechanism rather than a bare
``asyncio.gather`` (the lane difference vs. pydantic-ai / beeai): a ``dispatch``
step emits ``n`` :class:`_BranchEvent` via ``ctx.send_event``; a ``run_branch``
step declared with ``num_workers`` consumes them concurrently; and a ``collect``
step uses ``ctx.collect_events`` to barrier until all ``n`` branch results are in
(Req 4.4).

Under that worker pool the order in which branches reach the model is a
scheduler-dependent permutation. Each branch claims its ``index`` from a shared
counter the instant its ``acomplete`` call returns (no ``await`` between the call
and the claim), so ``index`` tracks completion order; ``collect_events`` returns
events in completion order and the explicit sort by ``index`` always restores an
ascending ``index`` sequence (the *order* is deterministic, Req 4.4). *Which*
output lands at a given ``index`` follows completion order: under the synchronous
offline fakes used in tests, completion order equals call order, so branch
``index`` carries the matching scripted output deterministically. Against a
concurrent real provider completion order is not fixed, so the output-to-index
assignment is not pinned — voting majority is order-insensitive, but a
sectioning ``aggregate`` may order its sections differently across runs.

Observability is OpenInference's process-global ``LlamaIndexInstrumentor``
(plan §9, Req 9.1): callers install it via
:func:`patterns_llamaindex.observability.instrument_llamaindex`. This module
embeds no instrumentation hook, matching the routing / orchestrator-workers /
prompt-chaining lanes.
"""

from __future__ import annotations

import itertools
from collections import Counter
from typing import TYPE_CHECKING, Literal

# `step` lacks complete stubs upstream; ignore is scoped to that name.
from llama_index.core.workflow import (
    Context,
    Event,
    StartEvent,
    StopEvent,
    Workflow,
    step,  # pyright: ignore[reportUnknownVariableType]
)
from patterns_contracts import Branch, ParallelResult

if TYPE_CHECKING:
    from llama_index.core.llms import LLM

__all__ = ["ParallelizationWorkflow", "run_parallelization"]


_FANOUT_WORKERS = 8
"""Worker-pool size for the ``run_branch`` step. LlamaIndex bounds step
concurrency by ``num_workers`` (a genuine difference from ``asyncio.gather``'s
unbounded fan-out); 8 comfortably covers the default ``n=3`` and the test
fan-outs. Larger ``n`` still completes correctly — branches beyond the pool size
run as workers free up — only with less in-flight parallelism."""

_SECTIONING_INSTRUCTIONS = (
    "You are one worker among several handling a larger task in parallel. "
    "Contribute only your own distinct portion of the task, concisely, without "
    "attempting the portions the other workers cover."
)

_VOTING_INSTRUCTIONS = (
    "You are an independent solver. Produce your own best complete answer to "
    "the task. Other solvers answer the same task in parallel; do not coordinate."
)


def _aggregate_sectioning(branches: list[Branch]) -> str:
    """Merge section outputs in ascending index order (Req 4.2)."""
    return "\n".join(branch.output for branch in branches)


def _aggregate_voting(branches: list[Branch]) -> str:
    """Resolve the branch outputs to a majority vote (Req 4.3).

    ``branches`` is in ascending index order, so the ``Counter`` encounters
    outputs lowest-index-first. ``most_common(1)`` returns the highest-count
    output and, on a tie, the one encountered first (lowest index) — a
    deterministic, index-ascending tie-break (Req 4.4). ``branches`` is
    non-empty (``n >= 1`` is enforced upstream), so the indexing is safe.
    """
    counts = Counter(branch.output for branch in branches)
    return counts.most_common(1)[0][0]


class _BranchEvent(Event):
    """One fan-out branch: the task to run on this worker."""

    task: str


class _BranchDoneEvent(Event):
    """A completed branch, tagged with its completion-order ``index``."""

    index: int
    output: str


class ParallelizationWorkflow(Workflow):
    """Fan ``task`` out to ``n`` workers, then aggregate by ``variant``."""

    def __init__(
        self,
        llm: LLM,
        *,
        variant: Literal["sectioning", "voting"],
        n: int,
        **kwargs: object,
    ) -> None:
        """Store the LLM and fan-out config; remaining kwargs go to ``Workflow``."""
        # Workflow.__init__ stub types **kwargs narrowly and rejects object.
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._llm = llm
        # Annotate explicitly: pyright widens a Literal stored in an unannotated
        # mutable attribute to ``str``, which would break the ParallelResult
        # construction in ``collect`` (variant is a closed Literal there).
        self._variant: Literal["sectioning", "voting"] = variant
        self._n = n
        self._instructions = (
            _SECTIONING_INSTRUCTIONS if variant == "sectioning" else _VOTING_INSTRUCTIONS
        )
        # Shared counter claimed at branch completion (see module docstring).
        self._index_counter = itertools.count()

    @step
    async def dispatch(self, ev: StartEvent, ctx: Context) -> _BranchEvent | None:
        """Emit ``n`` identical branch events for the worker pool (Req 4.4)."""
        task = str(ev.get("task"))
        for _ in range(self._n):
            ctx.send_event(_BranchEvent(task=task))
        return None

    @step(num_workers=_FANOUT_WORKERS)  # pyright: ignore[reportUntypedFunctionDecorator]
    async def run_branch(self, ev: _BranchEvent) -> _BranchDoneEvent:
        """Run one branch and claim its completion-order index (Req 4.4)."""
        prompt = f"{self._instructions}\n\nUser task: {ev.task}"
        response = await self._llm.acomplete(prompt)
        # Claim the index the instant the model responds: completion order tracks
        # the order outputs were produced, independent of worker interleaving.
        return _BranchDoneEvent(index=next(self._index_counter), output=str(response))

    @step
    async def collect(self, ev: _BranchDoneEvent, ctx: Context) -> StopEvent | None:
        """Barrier on all ``n`` branches, restore index order, then aggregate."""
        done = ctx.collect_events(ev, [_BranchDoneEvent] * self._n)
        if done is None:
            # Not all branches are in yet; this invocation buffers and yields.
            return None
        branches = sorted(
            (Branch(index=item.index, output=item.output) for item in done),
            key=lambda branch: branch.index,
        )
        aggregate = (
            _aggregate_sectioning(branches)
            if self._variant == "sectioning"
            else _aggregate_voting(branches)
        )
        return StopEvent(
            result=ParallelResult(variant=self._variant, branches=branches, aggregate=aggregate)
        )


async def run_parallelization(
    task: str,
    *,
    variant: Literal["sectioning", "voting"],
    llm: LLM,
    n: int = 3,
    timeout: float = 120.0,
) -> ParallelResult:
    """Fan ``task`` out across ``n`` parallel branches and aggregate them.

    Args:
        task: The user task to fan out.
        variant: ``"sectioning"`` asks each worker for a distinct portion of the
            task; ``"voting"`` runs the same task ``n`` times and takes the
            majority.
        llm: LlamaIndex LLM powering every branch (DI seam shared with the other
            patterns). Tests inject ``VotingLLM``; the integration lane injects
            an Ollama-backed model.
        n: Number of parallel branches. Must be >= 1.
        timeout: Workflow timeout in seconds (generous for local models).

    Returns:
        A :class:`~patterns_contracts.ParallelResult` whose ``branches`` are
        restored in ascending ``index`` order and whose ``aggregate`` is the
        merged sections (sectioning) or the majority vote (voting).

    Raises:
        ValueError: If ``n`` is not positive — a zero/negative fan-out would
            silently produce an empty parallel run.
    """
    if n < 1:
        msg = f"n must be >= 1, got {n}"
        raise ValueError(msg)

    workflow = ParallelizationWorkflow(llm=llm, variant=variant, n=n, timeout=timeout)
    # workflow.run's return type is partially unknown upstream; the isinstance
    # guard below narrows it for both pyright and runtime.
    result = await workflow.run(task=task)  # pyright: ignore[reportUnknownVariableType]
    if not isinstance(result, ParallelResult):  # pragma: no cover - defensive guard
        # Contract guard, not a debug assert: keep it under ``python -O`` too.
        # ``collect`` always returns a ParallelResult, so this is unreachable in
        # practice; it exists so a future workflow refactor fails loudly.
        msg = "workflow did not return a ParallelResult"
        raise TypeError(msg)
    return result
