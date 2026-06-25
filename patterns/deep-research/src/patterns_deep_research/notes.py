"""Structured note-taking + compaction for the Deep Research lane (Anthropic context engineering).

A *runnable demonstration* of two techniques from Anthropic's "Effective context
engineering for AI agents", applied to the sub-researcher reflect loop in
:mod:`patterns_deep_research.researcher`.

That loop currently re-injects the **entire** gathered-results digest
(``researcher._results_digest``) into every reflect turn, so the prompt grows with
each search and the model re-reads low-signal text token by token. This module
keeps an external, distilled **notebook** instead:

* **Structured note-taking** — each retrieved ``SearchResult`` is reduced to one
  high-signal *key point* (its first sentence, truncated) and kept as a
  :class:`ResearchNote`, the agent's external memory rather than raw transcript.
* **Compaction** — notes are deduplicated by source anchor (highest score wins)
  and capped to the top ``max_notes`` by score, yielding the "smallest set of
  high-signal tokens" the reflect turn actually needs.

``compact_digest`` is signature-compatible with ``researcher._results_digest`` (it
takes the gathered ``SearchResult`` list and returns a prompt string), so it is a
drop-in at that seam — see ``docs/context-engineering.md`` for the one-line swap.
Every function is deterministic and model-free, so the notebook unit-tests offline
exactly like the rest of the lane.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

# ``ResearchNote`` is the promoted single-source contract (patterns_contracts),
# instantiated at runtime in ``distill_notes`` — not a local redefinition
# (Spec 010 Req 2.1). The shape and frozen immutability live in the contract.
from patterns_contracts import ResearchNote

if TYPE_CHECKING:
    from collections.abc import Sequence

    from patterns_contracts import SearchResult

__all__ = [
    "ResearchNote",
    "compact_digest",
    "distill_notes",
    "render_notebook",
]

_DEFAULT_MAX_NOTES: Final = 5
"""Compaction budget: how many high-signal notes the notebook retains by default."""
_DEFAULT_KEY_POINT_CHARS: Final = 120
"""Truncation cap for a single note's key point, keeping each line high-signal."""
_TRUNCATION_MARKER: Final = "…"
"""Suffix appended to a key point that was shortened, so truncation stays visible."""
_EMPTY_NOTEBOOK: Final = "(no notes yet)"
"""Rendered placeholder when no results have been gathered, mirroring the lane idiom."""


def _key_point(snippet: str, limit: int) -> str:
    """Reduce a result snippet to its first sentence, truncated to ``limit`` chars.

    Splitting on the first ``". "`` keeps the lead sentence (the highest-signal
    part of a snippet) and drops the trailing detail; a lone trailing period is
    stripped so the key point reads cleanly.
    """
    head = snippet.strip().split(". ", 1)[0].strip().rstrip(".")
    if len(head) <= limit:
        return head
    return head[:limit].rstrip() + _TRUNCATION_MARKER


def distill_notes(
    results: Sequence[SearchResult],
    *,
    max_notes: int = _DEFAULT_MAX_NOTES,
    key_point_chars: int = _DEFAULT_KEY_POINT_CHARS,
) -> list[ResearchNote]:
    """Distil gathered results into the top high-signal notes (compaction).

    Args:
        results: The ``SearchResult``s gathered so far in the reflect loop.
        max_notes: Cap on retained notes — the compaction budget. Must be >= 1.
        key_point_chars: Truncation cap for each note's key point. Must be >= 1.

    Returns:
        At most ``max_notes`` deduplicated notes (one per ``source``/``locator``
        anchor, highest score wins), ordered by descending score with a
        deterministic ``(source, locator)`` tie-break.

    Raises:
        ValueError: If ``max_notes`` or ``key_point_chars`` is not positive —
            either would empty or corrupt the notebook rather than fail loudly.
    """
    if max_notes < 1:
        msg = f"max_notes must be >= 1, got {max_notes}"
        raise ValueError(msg)
    if key_point_chars < 1:
        msg = f"key_point_chars must be >= 1, got {key_point_chars}"
        raise ValueError(msg)

    best: dict[tuple[str, str], SearchResult] = {}
    for result in results:
        key = (result.source, result.locator)
        current = best.get(key)
        if current is None or result.score > current.score:
            best[key] = result

    ranked = sorted(
        best.values(), key=lambda result: (-result.score, result.source, result.locator)
    )
    return [
        ResearchNote(
            source=result.source,
            locator=result.locator,
            key_point=_key_point(result.snippet, key_point_chars),
            score=result.score,
        )
        for result in ranked[:max_notes]
    ]


def render_notebook(notes: Sequence[ResearchNote]) -> str:
    """Render notes as a compact, deterministic high-signal prompt block."""
    if not notes:
        return _EMPTY_NOTEBOOK
    return "\n".join(f"- [{note.source}#{note.locator}] {note.key_point}" for note in notes)


def compact_digest(
    results: Sequence[SearchResult],
    *,
    max_notes: int = _DEFAULT_MAX_NOTES,
    key_point_chars: int = _DEFAULT_KEY_POINT_CHARS,
) -> str:
    """Token-efficient drop-in for ``researcher._results_digest``.

    Distils ``results`` into the top ``max_notes`` notes and renders them as a
    compact notebook block — the same ``Sequence[SearchResult] -> str`` shape the
    reflect loop already feeds its prompt, but bounded to the high-signal subset.

    Args:
        results: The ``SearchResult``s gathered so far in the reflect loop.
        max_notes: Compaction budget forwarded to :func:`distill_notes`.
        key_point_chars: Truncation cap forwarded to :func:`distill_notes`.

    Returns:
        A compact notebook string suitable for the reflect prompt's results block.
    """
    return render_notebook(
        distill_notes(results, max_notes=max_notes, key_point_chars=key_point_chars)
    )
