"""Smoke + hermetic-guard tests for the SSE delivery lane (Spec 008-2c Req 1.1/1.3/1.4, 5.1).

Three concerns live here:

* the lane package ``patterns_sse`` imports cleanly (Req 1.1 — the ``--locked`` closure
  resolves and the editable wheel builds);
* importing it pulls in **no sibling lane** (NFR-3 / Req 1.3) — contract sharing flows only
  through the ``patterns_contracts`` path dependency, intentionally absent from the forbidden set;
* a *fake one-pass* through the whole delivery pipeline — ``create_app`` driven by the offline
  ``ScriptedEventSource`` over ``ASGITransport`` — completes with **zero network I/O** under a
  socket guard that loud-fails on any reach (Req 5.1). A companion case proves the R-2 backstop
  bounds even a producer that never emits its terminal marker, so an offline run always
  *completes* rather than wedging the in-process transport.

The hermetic guard mirrors the RAG lane's ``block_network`` (Spec 007-2b): it targets internet
*reach*, delegating AF_UNIX and other local sockets (asyncio's self-pipe) to the genuine
implementation so the in-process ASGI drive runs untouched.
"""

from __future__ import annotations

import importlib
import socket
import sys
from typing import TYPE_CHECKING

import httpx
import pytest
from patterns_contracts import CompletedEvent

from patterns_sse import create_app, parse_sse_events
from patterns_sse.app import _MAX_EVENTS  # pyright: ignore[reportPrivateUsage]
from tests.support.scripted_source import ScriptedEventSource

if TYPE_CHECKING:
    from collections.abc import Callable

# Sibling lanes the SSE lane must never import (NFR-3 / Req 1.3). Contract
# sharing is allowed and flows only through the `patterns_contracts` path
# dependency, which is intentionally absent from this set.
SIBLING_LANES = frozenset(
    {
        "patterns_pydantic_ai",
        "patterns_beeai",
        "patterns_llamaindex",
        "patterns_rag",
    }
)

# Internet socket families the hermetic guard rejects. AF_UNIX and the like are delegated to
# the real connect so the guard targets network *reach*, not in-process IPC (asyncio self-pipe).
_INET_FAMILIES = frozenset({socket.AF_INET, socket.AF_INET6})

# The address shape ``socket.connect`` / ``connect_ex`` accept (typeshed's private ``_Address``).
_Address = tuple[object, ...] | str | bytes


def test_patterns_sse_imports() -> None:
    import patterns_sse

    assert patterns_sse.__name__ == "patterns_sse"


def test_no_sibling_lane_imports() -> None:
    # Import for its side effect: populate sys.modules without binding a name
    # (keeps pyright strict's reportUnusedImport quiet).
    importlib.import_module("patterns_sse")

    leaked = SIBLING_LANES & set(sys.modules)
    assert not leaked, f"SSE lane must not import sibling lanes: {sorted(leaked)}"


class NetworkReachError(RuntimeError):
    """Raised when a unit-lane code path attempts to reach the network (Req 5.1)."""


@pytest.fixture
def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Loud-fail on any internet socket connect or DNS lookup (hermetic guard, Req 5.1).

    Installed around the fake one-pass so an accidental reach — an un-injected real producer,
    an OTLP export, a stray HTTP client — raises ``NetworkReachError`` instead of silently
    performing I/O. The offline pipeline (``ASGITransport`` drives the app in-process) opens no
    internet socket, so any AF_INET/AF_INET6 connect (sync or asyncio's ``connect_ex``) or
    ``getaddrinfo`` call is a regression. AF_UNIX and other local sockets are delegated to the
    genuine implementation so the event loop's self-pipe keeps working.
    """

    def _make_guard(real: Callable[[socket.socket, _Address], object]) -> Callable[..., object]:
        def _guard(self: socket.socket, address: _Address) -> object:
            if self.family in _INET_FAMILIES:
                msg = f"hermetic unit lane reached the network: {address!r} (Req 5.1)"
                raise NetworkReachError(msg)
            return real(self, address)  # genuinely local (AF_UNIX etc.)

        return _guard

    def _guarded_getaddrinfo(*args: object, **kwargs: object) -> object:
        msg = f"hermetic unit lane attempted DNS resolution: {args!r} (Req 5.1)"
        raise NetworkReachError(msg)

    # Read the real callables before patching so the delegate path cannot re-enter the guard.
    monkeypatch.setattr(socket.socket, "connect", _make_guard(socket.socket.connect))
    monkeypatch.setattr(socket.socket, "connect_ex", _make_guard(socket.socket.connect_ex))
    monkeypatch.setattr(socket, "getaddrinfo", _guarded_getaddrinfo)


async def _post_run(app: object, payload: dict[str, object]) -> httpx.Response:
    """POST ``/sse/runs`` over ASGITransport and return the fully buffered response."""
    transport = httpx.ASGITransport(app=app)  # pyright: ignore[reportArgumentType]
    async with httpx.AsyncClient(transport=transport, base_url="http://sse") as client:
        return await client.post("/sse/runs", json=payload)


def test_block_network_guard_loud_fails_on_internet_connect(block_network: None) -> None:
    # Load-bearing proof the guard is not vacuous: a real AF_INET connect must be intercepted
    # before any I/O (a loopback closed port would otherwise raise ConnectionRefusedError).
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock,
        pytest.raises(NetworkReachError),
    ):
        sock.connect(("127.0.0.1", 9))


async def test_fake_one_pass_runs_hermetically(block_network: None) -> None:
    # Full delivery pipeline under the guard: create_app -> ScriptedEventSource over
    # ASGITransport, all offline. Reaching the network anywhere raises NetworkReachError (Req 5.1).
    app = create_app(event_source=ScriptedEventSource())
    resp = await _post_run(app, {"query": "weather"})

    assert resp.status_code == 200
    events = parse_sse_events(resp.text)
    # The run completes offline: a terminal `completed` marker ends the stream (R4.4).
    assert events[-1].type == "completed"
    assert any(isinstance(event, CompletedEvent) for event in events)


async def test_runaway_producer_is_bounded_by_the_backstop(block_network: None) -> None:
    # An offline run must *complete* even when the producer never reaches its terminal marker:
    # the R-2 backstop caps the stream at `_MAX_EVENTS` and then closes it with an explicit
    # `error` marker -- never a silent truncation (R4.3) and always a terminal marker (R4.4) --
    # so ASGITransport (which buffers the whole finite stream, ADR-4a) cannot hang. Scripted with
    # > `_MAX_EVENTS` tokens so the producer's own `completed` sits beyond the cap.
    runaway_tokens = tuple("x" for _ in range(_MAX_EVENTS + 1))
    app = create_app(event_source=ScriptedEventSource(tokens=runaway_tokens))
    resp = await _post_run(app, {"query": "weather"})

    events = parse_sse_events(resp.text)
    # `_MAX_EVENTS` capped events plus exactly one terminal `error` marker the backstop appends.
    assert len(events) == _MAX_EVENTS + 1
    assert events[-1].type == "error"  # the backstop terminates explicitly (R4.4), never silent
    assert not any(event.type == "completed" for event in events)  # producer's marker unreached
