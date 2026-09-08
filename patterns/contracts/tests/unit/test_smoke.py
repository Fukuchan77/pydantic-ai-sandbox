"""Smoke test for the contracts package: import + hermetic-guard proof (X-2).

Load-bearing proof that the lane's autouse ``block_network`` socket guard
(``tests/unit/conftest.py``) actually fires -- ``patterns_contracts`` should
never touch the network at all (Principle III / NFR-5), so this guard should
never trip in normal operation, but must be proven non-vacuous all the same.
"""

from __future__ import annotations

import socket

import pytest

from tests.support.hermetic import NetworkReachError


def test_patterns_contracts_imports() -> None:
    import patterns_contracts

    assert patterns_contracts.__name__ == "patterns_contracts"


def test_block_network_guard_loud_fails_on_internet_connect() -> None:
    # Load-bearing proof the autouse guard is not vacuous: a real AF_INET connect must be
    # intercepted before any I/O (a loopback closed port would otherwise raise
    # ConnectionRefusedError).
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock,
        pytest.raises(NetworkReachError),
    ):
        sock.connect(("127.0.0.1", 9))
