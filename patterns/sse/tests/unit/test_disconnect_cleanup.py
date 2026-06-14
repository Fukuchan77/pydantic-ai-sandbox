"""Client disconnect stops the body generator and releases the producer (R6.1/6.2/6.3).

Two complementary layers, per research.md I-4 / ADR-4:

* **Scope-injected disconnect (the R6.2 primary technique).** The same ASGI app
  is driven in-process by ``asgi_driver`` while a ``ScriptedEventSource`` parks
  mid-stream (``block_after``); an injected ``http.disconnect`` fires
  sse-starlette's ``_listen_for_disconnect``, cancelling its task group so the
  parked producer receives ``CancelledError``. We assert the producer saw the
  cancellation (``cancelled``), ran its ``finally`` (``released``), and that only
  the pre-disconnect prefix reached the wire -- never ``completed`` and never an
  ``error`` event (the cancellation is propagated, not masked, R6.3).
* **Direct body-generator drive (the R6.1/6.3 complement).** ``_event_stream`` is
  driven directly: ``aclose()`` (``GeneratorExit``) and the cooperative
  ``is_disconnected`` break must both run the ``finally`` that releases the
  injected producer, with no network and no real socket.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from patterns_contracts import CompletedEvent, ErrorEvent

from patterns_sse import create_app, parse_sse_events
from patterns_sse.app import (
    _event_stream,  # pyright: ignore[reportPrivateUsage]  # drive the body generator directly for the GeneratorExit / cooperative-break paths (R6.1)
)
from tests.support.asgi_driver import drive_until_disconnect
from tests.support.scripted_source import ScriptedEventSource

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from starlette.requests import Request


class _AlreadyDisconnected:
    """Minimal ``Request`` stand-in whose ``is_disconnected`` is already true."""

    async def is_disconnected(self) -> bool:
        return True


class _NeverDisconnected:
    """Minimal ``Request`` stand-in that never reports a disconnect."""

    async def is_disconnected(self) -> bool:
        return False


async def test_scope_disconnect_cancels_producer_and_runs_cleanup() -> None:
    # block_after=2 yields `step_started` + `tool_called`, then parks on the gate.
    # disconnect_after=2 injects `http.disconnect` once those two frames are on
    # the wire, so sse-starlette cancels the task group while the producer is
    # parked -> it receives CancelledError mid-stream (R6.2).
    source = ScriptedEventSource(block_after=2)
    app = create_app(event_source=source)

    result = await drive_until_disconnect(app, query="weather", disconnect_after=2)

    assert result.injected_disconnect is True  # the http.disconnect path actually fired (ADR-4)
    assert source.cancelled is True  # producer received CancelledError, not silent close (R6.2/6.3)
    assert source.released is True  # its `finally` ran -> resources released (R6.1)
    # Only the pre-disconnect prefix is delivered; the run never completes.
    delivered = parse_sse_events(result.body_text)
    assert [event.type for event in delivered] == ["step_started", "tool_called"]
    assert not any(isinstance(event, CompletedEvent) for event in delivered)


async def test_cancellation_is_propagated_not_masked_as_error() -> None:
    # block_after=3 parks after `step_started` + `tool_called` + one token. The
    # injected disconnect must propagate the CancelledError (R6.3) -- it is never
    # swallowed nor rewritten into a terminal `error` event by the app's
    # `except Exception` branch (CancelledError is not an Exception).
    source = ScriptedEventSource(block_after=3)
    app = create_app(event_source=source)

    result = await drive_until_disconnect(app, query="weather", disconnect_after=3)

    assert source.cancelled is True
    delivered = parse_sse_events(result.body_text)
    assert not any(isinstance(event, ErrorEvent) for event in delivered)
    assert not any(isinstance(event, CompletedEvent) for event in delivered)


async def test_aclose_releases_producer_generator() -> None:
    # Driving the body generator directly and calling `aclose()` throws
    # GeneratorExit at its `yield`; the app's `finally: await aclose()` must then
    # release the injected producer (R6.1) -- proven by the producer's sentinel.
    source = ScriptedEventSource()
    request = cast("Request", _NeverDisconnected())
    # `_event_stream` is annotated `AsyncIterator`; it is an async *generator* at
    # run time, so narrow the type to reach `aclose` (the GeneratorExit seam).
    agen = cast(
        "AsyncGenerator[dict[str, str]]",
        _event_stream(request, source, "weather", None),
    )

    first = await agen.__anext__()
    assert first["event"] == "step_started"
    await agen.aclose()

    assert source.released is True


async def test_cooperative_disconnect_break_releases_producer() -> None:
    # When `request.is_disconnected()` is already true, the body generator breaks
    # before forwarding any event (R6.1 cooperative active-break) and its
    # `finally` still releases the producer.
    source = ScriptedEventSource()
    request = cast("Request", _AlreadyDisconnected())

    delivered = [event async for event in _event_stream(request, source, "weather", None)]

    assert delivered == []  # broke on the disconnect check before the first yield
    assert source.released is True
