"""Parallelization unit tests (Spec 006-2a Req 4.1/4.2/4.3/4.4, 9.2).

These tests exercise ``run_parallelization`` fully offline via the
``voting_model`` turn-cursor fake (Task 4.1), which replays one branch output
per model call. The suite covers both fan-out variants and the determinism
contract:

* **sectioning (Req 4.2)** — ``n`` independent branches run in parallel and the
  per-branch outputs are aggregated.
* **voting (Req 4.3)** — the same task fans out ``n`` ways; a split vote
  (e.g. 2:1) resolves to the majority output.
* **tie-break (Req 4.3/4.4)** — an even split resolves deterministically to the
  lowest branch ``index``.
* **order restoration (Req 4.4)** — ``branches`` come back in ascending
  ``index`` order, each carrying the output of the matching fan-out branch.
"""

from __future__ import annotations

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic_ai.models.instrumented import InstrumentationSettings

from patterns_pydantic_ai.observability import configure_tracing
from patterns_pydantic_ai.parallelization import run_parallelization
from tests.support.model_fakes import voting_model


async def test_sectioning_fans_out_n_branches_and_aggregates() -> None:
    # Req 4.2: each branch tackles a distinct section; aggregate spans all of
    # them, restored in ascending index order.
    model = voting_model(["section-zero", "section-one", "section-two"])

    result = await run_parallelization("plan an event", variant="sectioning", model=model, n=3)

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
    model = voting_model(["alpha", "alpha", "beta"])

    result = await run_parallelization("answer the question", variant="voting", model=model, n=3)

    assert result.variant == "voting"
    assert result.aggregate == "alpha"
    # All branches are still recorded in order regardless of the tally (Req 4.4).
    assert [branch.index for branch in result.branches] == [0, 1, 2]
    assert [branch.output for branch in result.branches] == ["alpha", "alpha", "beta"]


async def test_voting_tie_breaks_on_ascending_index() -> None:
    # Req 4.3/4.4: an even 2:2 split has no majority; the tie resolves to the
    # candidate first seen at the lowest branch index, deterministically.
    model = voting_model(["red", "blue", "red", "blue"])

    result = await run_parallelization("pick a color", variant="voting", model=model, n=4)

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
        model = voting_model(["b0", "b1", "b2", "b3", "b4"])

        result = await run_parallelization("survey", variant="sectioning", model=model, n=5)

        indices = [branch.index for branch in result.branches]
        assert indices == sorted(indices) == list(range(5))
        assert [branch.output for branch in result.branches] == ["b0", "b1", "b2", "b3", "b4"]


async def test_rejects_non_positive_branch_count() -> None:
    # A zero/negative fan-out would silently produce an empty parallel run.
    model = voting_model(["unused"])
    with pytest.raises(ValueError, match="n must be"):
        await run_parallelization("task", variant="voting", model=model, n=0)


async def test_parallelization_emits_spans_into_injected_exporter() -> None:
    # Req 9.2: an instrumented fan-out emits at least one (leaf gen_ai) span.
    exporter = InMemorySpanExporter()
    provider = configure_tracing(exporter)
    settings = InstrumentationSettings(tracer_provider=provider)
    model = voting_model(["x", "x", "y"])

    result = await run_parallelization(
        "hello", variant="voting", model=model, n=3, instrumentation=settings
    )

    assert result.aggregate == "x"
    spans = exporter.get_finished_spans()
    assert spans, "instrumented parallelization run must emit at least one span"
    # Req 9.3: assert only that leaf LLM spans exist; token aggregation is the
    # backend's concern (double-counting trap).
    assert any("gen_ai" in str(span.attributes) for span in spans)
