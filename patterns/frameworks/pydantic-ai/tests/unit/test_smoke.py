"""Smoke test (Spec 005 Req 4.2): import + one fake-model turn + typed result.

Also carries the load-bearing proof that the lane's autouse ``block_network``
socket guard (``tests/unit/conftest.py``, X-2) actually fires.
"""

from __future__ import annotations

import socket

import pytest
from pydantic_ai.models.test import TestModel

from patterns_pydantic_ai import RoutedAnswer, run_routing
from tests.support.hermetic import NetworkReachError


async def test_smoke_routing_with_testmodel() -> None:
    result = await run_routing("Why was I charged twice?", model=TestModel())
    assert isinstance(result, RoutedAnswer)
    assert result.route in {"billing", "technical", "general"}
    assert isinstance(result.answer, str)


def test_block_network_guard_loud_fails_on_internet_connect() -> None:
    # Load-bearing proof the autouse socket guard is not vacuous: a real AF_INET connect
    # must be intercepted before any I/O (a loopback closed port would otherwise raise
    # ConnectionRefusedError).
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock,
        pytest.raises(NetworkReachError),
    ):
        sock.connect(("127.0.0.1", 9))
