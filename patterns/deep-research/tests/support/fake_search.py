"""Deterministic offline ``SearchProvider`` for the Deep Research unit suite.

``FakeSearchProvider`` is the offline producer the search DI seam drives instead
of a real web client. It returns results from a fixed in-memory corpus
(``tests/fixtures/corpus.json``) sorted by descending ``score`` then ascending
``source`` — a stable, query-independent ordering so the whole pipeline is
byte-for-byte reproducible across runs (no network, no model, no randomness).

Three seams let tests drive the failure / empty paths without touching production
code:

* ``force_empty=True`` returns no results, so the compression step can be driven
  down the "no grounding" path;
* ``fail_at=N`` raises after the N-th call, proving the researcher surfaces a
  provider error rather than swallowing it;
* ``corpus=[...]`` injects an explicit result set for a focused test.

The relevance is intentionally query-independent: a fake's job is determinism,
not realism, and the "enough / keep searching" decision is the (scripted) model's,
not the provider's.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from patterns_contracts import SearchResult

if TYPE_CHECKING:
    from collections.abc import Sequence

    from patterns_contracts import SearchQuery

__all__ = ["FakeSearchProvider", "SearchUnavailableError"]

_CORPUS_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "corpus.json"


class SearchUnavailableError(RuntimeError):
    """Raised by the ``fail_at`` seam to simulate a search backend failure."""


def _load_default_corpus() -> list[SearchResult]:
    """Load the fixture corpus into ``SearchResult``s, in stable sorted order."""
    raw: list[dict[str, object]] = json.loads(_CORPUS_PATH.read_text(encoding="utf-8"))
    results = [SearchResult.model_validate(entry) for entry in raw]
    return _sorted(results)


def _sorted(results: Sequence[SearchResult]) -> list[SearchResult]:
    """Sort by descending score then ascending source (deterministic tie-break)."""
    return sorted(results, key=lambda result: (-result.score, result.source))


class FakeSearchProvider:
    """A deterministic ``SearchProvider`` replaying a fixed corpus with failure seams."""

    def __init__(
        self,
        *,
        corpus: Sequence[SearchResult] | None = None,
        force_empty: bool = False,
        fail_at: int | None = None,
    ) -> None:
        """Configure the fixed corpus and the failure / empty seams.

        Args:
            corpus: Explicit results to return; defaults to the fixture corpus.
            force_empty: When ``True`` every search returns no results.
            fail_at: Raise ``SearchUnavailableError`` on the N-th call (1-based).
        """
        self._corpus = _sorted(corpus) if corpus is not None else _load_default_corpus()
        self._force_empty = force_empty
        self._fail_at = fail_at
        self.calls = 0

    async def search(self, query: SearchQuery, *, top_k: int) -> list[SearchResult]:
        """Return up to ``top_k`` corpus results (query-independent, deterministic)."""
        del query  # The corpus is fixed; the query does not steer offline output.
        self.calls += 1
        if self._fail_at is not None and self.calls >= self._fail_at:
            msg = f"fake search backend unavailable on call {self.calls}"
            raise SearchUnavailableError(msg)
        if self._force_empty:
            return []
        return self._corpus[:top_k]
