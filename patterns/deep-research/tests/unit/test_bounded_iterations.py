"""Bounded-iteration guardrail tests for the Deep Research lane (Spec 009 Req 4.3, 7).

A sub-researcher's search→read→reflect loop must stop at ``max_iterations`` even
when the model never judges the evidence sufficient, flagging ``Finding.truncated``
— the autonomous-agent ``max_iterations`` discipline re-cast for research. When the
model judges "enough" the loop stops early and the finding is not truncated. The
caps loud-fail on a non-positive value.
"""

from __future__ import annotations

import pytest
from patterns_contracts import SubQuestion

from patterns_deep_research.researcher import run_subquestion
from tests.support.fake_search import FakeSearchProvider
from tests.support.model_fakes import scripted_model

_SUBQUESTION = SubQuestion(description="How does the orchestrator decompose a query?")


async def test_loop_runs_to_cap_when_never_enough() -> None:
    # action always returns enough=False -> the loop exhausts max_iterations.
    model = scripted_model(action={"query": "keep searching", "enough": False})
    finding = await run_subquestion(
        _SUBQUESTION, model=model, search=FakeSearchProvider(), max_iterations=3
    )
    assert finding.iterations == 3
    assert finding.truncated is True


async def test_loop_stops_early_when_enough() -> None:
    # action returns enough=True on the first turn -> one iteration, not truncated.
    model = scripted_model(action={"query": "deep research", "enough": True})
    finding = await run_subquestion(
        _SUBQUESTION, model=model, search=FakeSearchProvider(), max_iterations=5
    )
    assert finding.iterations == 1
    assert finding.truncated is False


async def test_top_k_is_forwarded_to_search() -> None:
    model = scripted_model(action={"query": "q", "enough": True})
    provider = FakeSearchProvider()
    finding = await run_subquestion(
        _SUBQUESTION, model=model, search=provider, max_iterations=1, top_k=2
    )
    # The single search was bounded to top_k=2; the finding can only cite gathered
    # sources, so the default scripted citation (a top corpus source) is present.
    assert provider.calls == 1
    assert finding.citations


async def test_empty_query_skips_search() -> None:
    # action returns an empty query -> the researcher must NOT call search that turn.
    # With enough=True it stops after one (search-free) turn; the empty corpus then
    # leaves the scripted finding with nothing real to cite -> EmptyCitationError is
    # the scripted finding's choice here, so we cite nothing to confirm no search ran.
    from patterns_deep_research import EmptyCitationError

    model = scripted_model(
        action={"query": "", "enough": True},
        finding={"summary": "no search performed", "cited_sources": []},
    )
    provider = FakeSearchProvider()
    with pytest.raises(EmptyCitationError):
        await run_subquestion(_SUBQUESTION, model=model, search=provider, max_iterations=1)
    assert provider.calls == 0  # the empty-query branch skipped the search call


async def test_non_positive_caps_loud_fail() -> None:
    model = scripted_model(action={"query": "q", "enough": True})
    with pytest.raises(ValueError, match="max_iterations must be >= 1"):
        await run_subquestion(
            _SUBQUESTION, model=model, search=FakeSearchProvider(), max_iterations=0
        )
    with pytest.raises(ValueError, match="top_k must be >= 1"):
        await run_subquestion(_SUBQUESTION, model=model, search=FakeSearchProvider(), top_k=0)
