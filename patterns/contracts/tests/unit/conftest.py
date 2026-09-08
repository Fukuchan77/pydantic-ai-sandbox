"""Hermetic-guard fixture for the contracts unit suite (X-2).

``patterns_contracts`` is pure ``pydantic`` models plus typing primitives
(Principle III / NFR-5) with no I/O of any kind, so this suite should never
touch the network. The autouse ``block_network`` fixture makes that an
enforced invariant rather than an assumption: any accidental internet reach
turns into a loud ``NetworkReachError`` instead of silent I/O.

Targets internet *reach* (AF_INET/AF_INET6 connect + DNS), delegating AF_UNIX
and other local sockets (asyncio's self-pipe) to the genuine implementation so
the event loop keeps working. ``test_smoke.py`` proves the guard is not
vacuous. This lane has no ``tests/integration`` directory, so the guard
applies to the whole suite.
"""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING

import pytest

from tests.support.hermetic import NetworkReachError

if TYPE_CHECKING:
    from collections.abc import Callable

_INET_FAMILIES = frozenset({socket.AF_INET, socket.AF_INET6})
_Address = tuple[object, ...] | str | bytes


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Loud-fail on any internet socket connect or DNS lookup (hermetic guard)."""

    def _make_guard(real: Callable[[socket.socket, _Address], object]) -> Callable[..., object]:
        def _guard(self: socket.socket, address: _Address) -> object:
            if self.family in _INET_FAMILIES:
                msg = f"hermetic unit lane reached the network: {address!r}"
                raise NetworkReachError(msg)
            return real(self, address)  # genuinely local (AF_UNIX etc.)

        return _guard

    def _guarded_getaddrinfo(*args: object, **kwargs: object) -> object:
        msg = f"hermetic unit lane attempted DNS resolution: {args!r}"
        raise NetworkReachError(msg)

    monkeypatch.setattr(socket.socket, "connect", _make_guard(socket.socket.connect))
    monkeypatch.setattr(socket.socket, "connect_ex", _make_guard(socket.socket.connect_ex))
    monkeypatch.setattr(socket, "getaddrinfo", _guarded_getaddrinfo)
