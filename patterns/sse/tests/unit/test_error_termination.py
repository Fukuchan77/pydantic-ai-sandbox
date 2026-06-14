"""Run-time errors terminate the stream with an ``error`` marker, never silently (R4.3 / R4.4).

Task 6 drives ``create_app`` with the offline ``ScriptedEventSource``'s ``fail_at``
seam, which raises a ``RuntimeError`` *after* yielding a chosen number of events --
standing in for a mid-run agent failure. Over ``httpx.ASGITransport`` (the finite
stream is fully buffered, ADR-4a) the delivered wire stream must then:

* end with a single terminal ``error`` event carrying the failure summary, proving
  the exception was surfaced rather than swallowed (R4.3); and
* stop there -- no ``completed`` and nothing after the ``error`` marker, so the
  stream ends on exactly one terminal marker (R4.4).

The producer's own ``except CancelledError`` / ``finally`` bookkeeping is out of
scope here (that is Task 7's disconnect path); this file isolates the *error*
termination contract the app's ``except Exception -> ErrorEvent`` branch owns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from patterns_contracts import CompletedEvent, ErrorEvent

from patterns_sse import create_app, parse_sse_events
from tests.support.scripted_source import ScriptedEventSource

if TYPE_CHECKING:
    from patterns_contracts import SseEvent


async def _post_run(source: ScriptedEventSource, query: str) -> list[SseEvent]:
    """POST ``/sse/runs`` over ASGITransport and return the parsed wire events."""
    app = create_app(event_source=source)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://sse") as client:
        resp = await client.post("/sse/runs", json={"query": query})
    return parse_sse_events(resp.text)


async def test_mid_run_error_is_delivered_as_terminal_error_event() -> None:
    # fail_at=2 yields `step_started` + `tool_called`, then raises before any token.
    # The app must convert that into a trailing `error` event (R4.3) -- the partial
    # stream up to the failure point is preserved, then terminated, not crashed.
    events = await _post_run(ScriptedEventSource(fail_at=2), "weather")

    types = [event.type for event in events]
    assert types == ["step_started", "tool_called", "error"]
    assert isinstance(events[-1], ErrorEvent)
    # Silent truncation would have stopped at the two real events with no marker;
    # the stream never reaches `completed` because the run errored.
    assert not any(isinstance(event, CompletedEvent) for event in events)


async def test_error_event_carries_the_failure_summary_not_swallowed() -> None:
    # A swallowed exception (`except Exception: pass`) would deliver zero error
    # events; surfacing it means exactly one, carrying the formatted summary so a
    # client can see *what* failed (R4.3).
    source = ScriptedEventSource(fail_at=1, fail_message="boom during run")
    events = await _post_run(source, "weather")

    errors = [event for event in events if isinstance(event, ErrorEvent)]
    assert len(errors) == 1
    assert errors[0].message == "RuntimeError: boom during run"


async def test_error_is_the_terminal_marker_and_nothing_follows() -> None:
    # fail_at=4 fails mid-token-stream (after step + tool + 2 tokens). R4.4: the
    # stream ends on exactly one terminal marker -- the `error` is last and is the
    # sole terminal event (no `completed` alongside it).
    events = await _post_run(ScriptedEventSource(fail_at=4), "weather")

    assert events[-1].type == "error"
    terminal = [e for e in events if isinstance(e, (CompletedEvent, ErrorEvent))]
    assert len(terminal) == 1
    assert isinstance(terminal[0], ErrorEvent)


async def test_failure_before_any_event_still_terminates_with_error() -> None:
    # Edge: fail_at=0 raises before the first yield. The stream still terminates
    # cleanly on a single `error` marker rather than emitting an empty body (R4.4).
    events = await _post_run(ScriptedEventSource(fail_at=0), "weather")

    assert [event.type for event in events] == ["error"]
    assert isinstance(events[0], ErrorEvent)


async def test_error_message_is_a_single_line_summary() -> None:
    # The error payload is a one-line `<ExcType>: <msg>` summary -- no multi-line
    # traceback leaks onto the wire (R8.3 reinforces the `error` event's shape).
    source = ScriptedEventSource(fail_at=3, fail_message="upstream timeout")
    events = await _post_run(source, "weather")

    error = next(event for event in events if isinstance(event, ErrorEvent))
    assert "\n" not in error.message
    assert "Traceback" not in error.message
    assert error.message == "RuntimeError: upstream timeout"
