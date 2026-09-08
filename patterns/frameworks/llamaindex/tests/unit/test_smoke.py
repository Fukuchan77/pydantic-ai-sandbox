"""Smoke test (Spec 005 Req 4.2): import + one fake-LLM turn + typed result.

Also carries the load-bearing proof that the lane's autouse ``block_network``
socket guard (``tests/unit/conftest.py``, X-2) actually fires.
"""

from __future__ import annotations

import socket

import pytest

from patterns_llamaindex import RoutedAnswer, run_routing
from tests.support.fake_llm import ScriptedLLM
from tests.support.hermetic import NetworkReachError


async def test_smoke_routing_with_scripted_llm() -> None:
    llm = ScriptedLLM(
        route_payload={"route": "general", "reasoning": "smoke"},
        text="hello from the fake",
    )
    result = await run_routing("ping", llm=llm)
    assert isinstance(result, RoutedAnswer)
    assert result.route == "general"
    assert result.answer == "hello from the fake"


def test_block_network_guard_loud_fails_on_internet_connect() -> None:
    # Load-bearing proof the autouse socket guard is not vacuous: a real AF_INET connect
    # must be intercepted before any I/O (a loopback closed port would otherwise raise
    # ConnectionRefusedError).
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock,
        pytest.raises(NetworkReachError),
    ):
        sock.connect(("127.0.0.1", 9))
