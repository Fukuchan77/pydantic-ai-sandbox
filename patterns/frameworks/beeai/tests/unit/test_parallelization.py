"""Parallelization unit tests — BeeAI lane (Spec 006-2a Req 4.1/4.2/4.3/4.4, 9.2).

These tests exercise ``run_parallelization`` fully offline via the
``VotingChatModel`` call-cursor fake (Task 4.2), which replays one branch output
per ``create`` call. The suite covers both fan-out variants and the determinism
contract:

* **sectioning (Req 4.2)** — ``n`` independent branches run in parallel and the
  per-branch outputs are aggregated.
* **voting (Req 4.3)** — the same task fans out ``n`` ways; a split vote
  (e.g. 2:1) resolves to the majority output.
* **tie-break (Req 4.3/4.4)** — an even split resolves deterministically to the
  lowest branch ``index``.
* **order restoration (Req 4.4)** — ``branches`` come back in ascending
  ``index`` order, each carrying the output of the matching fan-out branch.

Observability for the BeeAI lane is the manual-span fallback (Req 9.1): the
span test wraps the run with :func:`patterns_beeai.observability.traced`,
mirroring ``test_prompt_chaining.py``.
"""

from __future__ import annotations

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from patterns_beeai.observability import configure_tracing, traced
from patterns_beeai.parallelization import run_parallelization
from tests.support.fake_chat_model import VotingChatModel


async def test_sectioning_fans_out_n_branches_and_aggregates() -> None:
    # Req 4.2: each branch tackles a distinct section; aggregate spans all of
    # them, restored in ascending index order.
    llm = VotingChatModel(["section-zero", "section-one", "section-two"])

    result = await run_parallelization("plan an event", variant="sectioning", llm=llm, n=3)

    assert result.variant == "sectioning"
    assert [branch.index for branch in result.branches] == [0, 1, 2]
    assert [branch.output for branch in result.branches] == [
        "section-zero",
        "section-one",
        "section-two",
    ]
    # Every branch output is carried into the aggregate (Req 4.2).
    for output in ("section-zero", "section-one", "section-two"):
        assert output in result.aggregate


async def test_voting_resolves_split_vote_to_majority() -> None:
    # Req 4.3: same task fanned out 3 ways with a 2:1 split -> majority "alpha".
    llm = VotingChatModel(["alpha", "alpha", "beta"])

    result = await run_parallelization("answer the question", variant="voting", llm=llm, n=3)

    assert result.variant == "voting"
    assert result.aggregate == "alpha"
    # All branches are still recorded in order regardless of the tally (Req 4.4).
    assert [branch.index for branch in result.branches] == [0, 1, 2]
    assert [branch.output for branch in result.branches] == ["alpha", "alpha", "beta"]


async def test_voting_tie_breaks_on_ascending_index() -> None:
    # Req 4.3/4.4: an even 2:2 split has no majority; the tie resolves to the
    # candidate first seen at the lowest branch index, deterministically.
    llm = VotingChatModel(["red", "blue", "red", "blue"])

    result = await run_parallelization("pick a color", variant="voting", llm=llm, n=4)

    assert result.aggregate == "red"
    assert [branch.output for branch in result.branches] == ["red", "blue", "red", "blue"]


async def test_branches_restored_in_index_order_under_parallel_fanout() -> None:
    # Req 4.4: branch i deterministically carries the i-th fan-out output even
    # though execution is parallel; the index sequence is strictly ascending.
    # Repeated so a regression that lets the fan-out interleave between the model
    # call and the index claim (reordering output vs. index) surfaces reliably
    # rather than as rare flakiness that a single run could pass by luck.
    for _ in range(30):
        # Recreate the cursor fake each iteration — it is stateful and exhausts
        # after n calls.
        llm = VotingChatModel(["b0", "b1", "b2", "b3", "b4"])

        result = await run_parallelization("survey", variant="sectioning", llm=llm, n=5)

        indices = [branch.index for branch in result.branches]
        assert indices == sorted(indices) == list(range(5))
        assert [branch.output for branch in result.branches] == ["b0", "b1", "b2", "b3", "b4"]


async def test_rejects_non_positive_branch_count() -> None:
    # A zero/negative fan-out would silently produce an empty parallel run.
    llm = VotingChatModel(["unused"])
    with pytest.raises(ValueError, match="n must be"):
        await run_parallelization("task", variant="voting", llm=llm, n=0)


async def test_parallelization_emits_spans_into_injected_exporter() -> None:
    # Req 9.2: an instrumented fan-out emits at least one span. The BeeAI lane
    # uses the manual-span fallback (Req 9.1), so the caller wraps the run in
    # traced, mirroring the other patterns.
    exporter = InMemorySpanExporter()
    provider = configure_tracing(exporter)
    llm = VotingChatModel(["x", "x", "y"])

    result = await traced(
        provider,
        "pattern.parallelization",
        run_parallelization("hello", variant="voting", llm=llm, n=3),
    )

    assert result.aggregate == "x"
    spans = exporter.get_finished_spans()
    assert spans, "instrumented parallelization run must emit at least one span"
    # Req 9.3: assert only that the (manual pattern-level) span exists; token
    # aggregation is the backend's concern (double-counting trap).
    assert any(span.name == "pattern.parallelization" for span in spans)
