"""Deterministic ``token`` increments: the fixed chunk list replays byte-identically (R5.3 / NFR-2).

Task 5 narrows the determinism guarantee to the ``token`` lane specifically: the
offline ``ScriptedEventSource`` supplies incremental tokens from a *fixed chunk
list*, so the ordered sequence of ``TokenEvent.text`` increments delivered over
``httpx.ASGITransport`` must be byte-for-byte identical across runs -- no model,
no network, no randomness (NFR-2, zero test flakiness).

This is distinct from ``test_stream_order``'s whole-stream equality: here we
isolate the token text increments and pin them to the exact configured chunks,
so a regression that merged, reordered, or perturbed token emission fails loudly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from patterns_contracts import TokenEvent

from patterns_sse import create_app, parse_sse_events
from tests.support.scripted_source import ScriptedEventSource

if TYPE_CHECKING:
    from fastapi import FastAPI


async def _token_increments(app: FastAPI, query: str) -> list[str]:
    """POST ``/sse/runs`` over ASGITransport and return the ordered ``token`` text increments."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://sse") as client:
        resp = await client.post("/sse/runs", json={"query": query})
    events = parse_sse_events(resp.text)
    return [event.text for event in events if isinstance(event, TokenEvent)]


async def test_token_increments_match_the_fixed_chunk_list() -> None:
    # An explicit chunk list pins the delivered increments to exactly what the
    # fake was scripted with -- proving the fake supplies fixed chunks verbatim,
    # not a join/re-split that could perturb the increment boundaries (R5.3).
    chunks = ("To", "ken", " stream")
    app = create_app(
        event_source=ScriptedEventSource(tokens=chunks, output="Token stream"),
    )
    assert await _token_increments(app, "weather") == list(chunks)


async def test_token_increments_are_byte_identical_across_runs() -> None:
    # Re-driving the same app must reproduce the increment sequence exactly; any
    # nondeterminism (ordering, chunk boundaries) would surface as inequality.
    app = create_app(event_source=ScriptedEventSource())
    runs = [await _token_increments(app, "weather") for _ in range(3)]
    assert runs[0] == runs[1] == runs[2]
    # The increments are non-trivial: guards against a vacuous empty-list match.
    assert len(runs[0]) >= 2


async def test_token_increments_are_stable_across_independent_sources() -> None:
    # Determinism must not hinge on reusing one source instance: two freshly
    # constructed apps/fakes with the same script deliver identical increments,
    # and the fixed script ignores the (differing) query (R5.3 / NFR-2).
    first = await _token_increments(create_app(event_source=ScriptedEventSource()), "a")
    second = await _token_increments(create_app(event_source=ScriptedEventSource()), "b")
    assert first == second
