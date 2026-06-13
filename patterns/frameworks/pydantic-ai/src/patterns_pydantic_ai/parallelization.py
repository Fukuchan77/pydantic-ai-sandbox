"""Parallelization pattern — PydanticAI implementation (Spec 006-2a Req 4).

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

Both variants fan out with ``asyncio.gather`` (Req 4.4). Each branch claims its
``index`` from a shared counter the moment its model call returns, so ``index``
tracks completion order and ``branches`` is always restored to an ascending
``index`` sequence (the *order* is deterministic). *Which* output lands at a
given ``index`` follows completion order: under the synchronous offline fakes
used in tests, completion order equals call order, so branch ``index`` carries
the matching scripted output deterministically. Against a concurrent real
provider completion order is not fixed, so the output-to-index assignment is not
pinned — voting majority is order-insensitive, but a sectioning ``aggregate``
may order its sections differently across runs.
"""

from __future__ import annotations

import asyncio
import itertools
from collections import Counter
from typing import TYPE_CHECKING, Literal

from patterns_contracts import Branch, ParallelResult
from pydantic_ai import Agent
from pydantic_ai.models.instrumented import instrument_model

if TYPE_CHECKING:
    from pydantic_ai.models import Model
    from pydantic_ai.models.instrumented import InstrumentationSettings

__all__ = ["run_parallelization"]


_SECTIONING_INSTRUCTIONS = (
    "You are one worker among several handling a larger task in parallel. "
    "Contribute only your own distinct portion of the task, concisely, without "
    "attempting the portions the other workers cover."
)

_VOTING_INSTRUCTIONS = (
    "You are an independent solver. Produce your own best complete answer to "
    "the task. Other solvers answer the same task in parallel; do not coordinate."
)


def _agent(model: Model, instructions: str) -> Agent[None, str]:
    """Construct a plain-text agent with shared settings."""
    return Agent[None, str](
        model=model,
        output_type=str,
        instructions=instructions,
        deps_type=type(None),
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


async def run_parallelization(
    task: str,
    *,
    variant: Literal["sectioning", "voting"],
    model: Model,
    n: int = 3,
    instrumentation: InstrumentationSettings | None = None,
) -> ParallelResult:
    """Fan ``task`` out across ``n`` parallel branches and aggregate them.

    Args:
        task: The user task to fan out.
        variant: ``"sectioning"`` asks each worker for a distinct portion of the
            task; ``"voting"`` runs the same task ``n`` times and takes the
            majority.
        model: PydanticAI model powering every branch (DI seam shared with the
            other patterns). Tests inject ``voting_model``; the integration lane
            injects an Ollama-backed model.
        n: Number of parallel branches. Must be >= 1.
        instrumentation: Optional ``InstrumentationSettings`` built from
            :func:`patterns_pydantic_ai.observability.configure_tracing`. When
            set the model is wrapped via ``instrument_model`` (V2 API) so
            ``gen_ai.*`` spans flow to the provider. ``None`` runs uninstrumented.

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

    resolved = instrument_model(model, instrumentation) if instrumentation else model
    instructions = _SECTIONING_INSTRUCTIONS if variant == "sectioning" else _VOTING_INSTRUCTIONS
    agent = _agent(resolved, instructions)
    index_counter = itertools.count()

    async def _run_branch() -> Branch:
        # Claim the index the instant the model responds: completion order
        # tracks the order outputs were produced (Req 4.4), independent of the
        # scheduler's fan-out interleaving.
        output = (await agent.run(task)).output
        return Branch(index=next(index_counter), output=output)

    branches = sorted(
        await asyncio.gather(*(_run_branch() for _ in range(n))),
        key=lambda branch: branch.index,
    )

    aggregate = (
        _aggregate_sectioning(branches) if variant == "sectioning" else _aggregate_voting(branches)
    )
    return ParallelResult(variant=variant, branches=branches, aggregate=aggregate)
