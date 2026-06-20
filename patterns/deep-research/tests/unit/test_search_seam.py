"""Search DI seam tests for the Deep Research lane (Spec 009 Req 4.2).

The ``FakeSearchProvider`` must structurally satisfy the ``SearchProvider``
Protocol and return results in a deterministic order (descending score, ascending
source) so the whole pipeline is reproducible. The failure / empty seams and the
``top_k`` bound are exercised here; the live ``load_search_provider`` loader
loud-fails without an explicit backend rather than silently faking.
"""

from __future__ import annotations

import pytest
from patterns_contracts import SearchQuery

from patterns_deep_research import SearchProvider, load_search_provider
from tests.support.fake_search import FakeSearchProvider, SearchUnavailableError


def test_fake_satisfies_search_provider_protocol() -> None:
    assert isinstance(FakeSearchProvider(), SearchProvider)


async def test_results_are_deterministic_and_score_sorted() -> None:
    provider = FakeSearchProvider()
    first = await provider.search(SearchQuery(text="anything"), top_k=4)
    second = await FakeSearchProvider().search(SearchQuery(text="other"), top_k=4)

    # Query-independent + reproducible across instances.
    assert [r.source for r in first] == [r.source for r in second]
    # Descending score order (the deterministic tie-break contract).
    assert [r.score for r in first] == sorted((r.score for r in first), reverse=True)


async def test_top_k_bounds_result_volume() -> None:
    provider = FakeSearchProvider()
    assert len(await provider.search(SearchQuery(text="q"), top_k=2)) == 2
    assert len(await provider.search(SearchQuery(text="q"), top_k=1)) == 1


async def test_force_empty_returns_nothing() -> None:
    provider = FakeSearchProvider(force_empty=True)
    assert await provider.search(SearchQuery(text="q"), top_k=5) == []


async def test_fail_at_seam_raises() -> None:
    provider = FakeSearchProvider(fail_at=1)
    with pytest.raises(SearchUnavailableError):
        await provider.search(SearchQuery(text="q"), top_k=5)


def test_load_search_provider_loud_fails_without_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEP_RESEARCH_SEARCH_BACKEND", raising=False)
    with pytest.raises(ValueError, match="DEEP_RESEARCH_SEARCH_BACKEND is unset"):
        load_search_provider()


def test_load_search_provider_rejects_unwired_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEP_RESEARCH_SEARCH_BACKEND", "tavily")
    with pytest.raises(ValueError, match="not wired into the runtime closure"):
        load_search_provider()
