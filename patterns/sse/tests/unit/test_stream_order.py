"""Happy-path SSE delivery: the ordered event stream round-trips via ASGITransport.

Drives ``create_app`` with the offline ``ScriptedEventSource`` over httpx's
``ASGITransport`` (ADR-4a: the finite stream is fully buffered in one body) and
asserts the design's delivery contract:

* the wire sequence preserves source order ``step_started -> tool_called* ->
  token* -> completed`` (R4.1);
* every ``data:`` payload validates back to its concrete contract member via the
  discriminated union, and re-``model_validate``s cleanly (R4.2 / R5.2);
* the run is reproducible and the endpoint validates its body before streaming
  (R3.1 / R5.1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest
from patterns_contracts import (
    CompletedEvent,
    StepStartedEvent,
    TokenEvent,
    ToolCalledEvent,
)

from patterns_sse import create_app, parse_sse_events
from tests.support.scripted_source import ScriptedEventSource

if TYPE_CHECKING:
    from fastapi import FastAPI


async def _post_run(app: FastAPI, query: str) -> httpx.Response:
    """POST ``/sse/runs`` over ASGITransport and return the fully buffered response."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://sse") as client:
        return await client.post("/sse/runs", json={"query": query})


async def test_stream_returns_event_stream_media_type() -> None:
    app = create_app(event_source=ScriptedEventSource())
    resp = await _post_run(app, "weather")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")


async def test_stream_preserves_canonical_event_order() -> None:
    app = create_app(event_source=ScriptedEventSource())
    resp = await _post_run(app, "weather")

    events = parse_sse_events(resp.text)
    types = [event.type for event in events]
    assert types == [
        "step_started",
        "tool_called",
        "token",
        "token",
        "token",
        "token",
        "completed",
    ]
    # The terminal marker ends the stream cleanly (R4.4) and nothing follows it.
    assert types[-1] == "completed"


async def test_stream_payloads_are_concrete_contract_members() -> None:
    app = create_app(event_source=ScriptedEventSource())
    resp = await _post_run(app, "weather")

    events = parse_sse_events(resp.text)
    assert [type(event) for event in events] == [
        StepStartedEvent,
        ToolCalledEvent,
        TokenEvent,
        TokenEvent,
        TokenEvent,
        TokenEvent,
        CompletedEvent,
    ]
    # R4.2: each delivered event re-validates from its own dump (model_validate).
    for event in events:
        assert type(event).model_validate(event.model_dump()) == event


async def test_token_increments_reconstruct_the_output() -> None:
    app = create_app(event_source=ScriptedEventSource())
    resp = await _post_run(app, "weather")

    events = parse_sse_events(resp.text)
    tokens = [event.text for event in events if isinstance(event, TokenEvent)]
    completed = [event for event in events if isinstance(event, CompletedEvent)]
    assert "".join(tokens) == "Hello world"
    assert len(completed) == 1
    assert completed[0].output == "Hello world"


async def test_stream_is_deterministic_across_runs() -> None:
    app = create_app(event_source=ScriptedEventSource())
    first = parse_sse_events((await _post_run(app, "weather")).text)
    second = parse_sse_events((await _post_run(app, "weather")).text)
    assert first == second


# Missing key, wrong type, empty string, and whitespace-only must all be rejected with 422
# *before* any streaming begins (R3.1; plan.md "空クエリ等の不正入力 -> 4xx"). The empty and
# whitespace cases pin the boundary the bare `str` type would otherwise let through.
@pytest.mark.parametrize("payload", [{}, {"query": 1}, {"query": ""}, {"query": "   "}])
async def test_missing_or_invalid_query_is_rejected_before_streaming(
    payload: dict[str, object],
) -> None:
    app = create_app(event_source=ScriptedEventSource())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://sse") as client:
        resp = await client.post("/sse/runs", json=payload)
    assert resp.status_code == 422
