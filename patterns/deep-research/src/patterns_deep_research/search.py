"""Search provider DI seam for the Deep Research lane (Spec 009 Req 4.2).

The lane src never reaches the web directly: a sub-researcher issues a
``SearchQuery`` to an injected ``SearchProvider``, the only door to the outside
world. This keeps the orchestration framework- and provider-agnostic (NFR-3) and
the whole unit suite hermetic — tests inject a deterministic in-memory fake
(``tests/support/fake_search.py``), never a network client.

``load_search_provider`` is the live escape hatch: it reads
``DEEP_RESEARCH_SEARCH_BACKEND`` and imports the heavy client *inside* the
function (lazy, so importing this module performs no I/O and pulls in no optional
dependency). The live backends are dev/integration-only and gated behind a second
flag (``RUN_INTEGRATION_SEARCH=1``); the unit suite and CI never call this.
Endpoints and API keys come from the environment (``TAVILY_API_KEY`` /
``SEARXNG_URL`` / …), never hardcoded (model-id / secret hygiene).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from patterns_contracts import SearchQuery, SearchResult

__all__ = ["SearchProvider", "load_search_provider"]


@runtime_checkable
class SearchProvider(Protocol):
    """Structural seam a sub-researcher calls to gather grounding results.

    Any object with a matching ``search`` coroutine satisfies it — the offline
    fake, a live web client, or a retriever over a local corpus. ``top_k`` bounds
    the result volume per call (an unbounded-consumption guard, Req 7).
    """

    async def search(self, query: SearchQuery, *, top_k: int) -> list[SearchResult]:
        """Return up to ``top_k`` results for ``query``, most relevant first."""
        ...


def load_search_provider() -> SearchProvider:
    """Build the live ``SearchProvider`` selected by ``DEEP_RESEARCH_SEARCH_BACKEND``.

    The client is imported lazily so this module stays I/O- and optional-dependency
    free at import time; only the gated live-search integration calls this. The
    backend's endpoint/key are read from the environment, never hardcoded.

    Returns:
        A live ``SearchProvider`` for the configured backend.

    Raises:
        ValueError: When ``DEEP_RESEARCH_SEARCH_BACKEND`` is unset or names an
            unknown backend — a misconfiguration that must fail loudly rather than
            silently fall back to a fake in a run the caller expected to be live.
    """
    backend = os.environ.get("DEEP_RESEARCH_SEARCH_BACKEND", "").strip().lower()
    if not backend:
        msg = (
            "DEEP_RESEARCH_SEARCH_BACKEND is unset; inject a SearchProvider explicitly "
            "(the offline fake for tests) or set a live backend for an online run."
        )
        raise ValueError(msg)
    # Live backends are dev/integration-only; the concrete adapter is built in the
    # gated integration suite where its client dependency is installed. Keeping the
    # construction out of the runtime closure preserves the hermetic unit lane.
    msg = (
        f"live search backend {backend!r} is not wired into the runtime closure; "
        "build the adapter in the gated integration suite (RUN_INTEGRATION_SEARCH=1)."
    )
    raise ValueError(msg)
