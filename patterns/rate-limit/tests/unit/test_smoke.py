"""Smoke, toolchain, and hermetic-guard tests for the rate-limit lane.

The toolchain assertions are the lane's reason to exist: if the lockfile ever
slid back under fastapi 0.137, starlette 1.0, or Python 3.15, every other test
here would still pass while verifying nothing the hub needs.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import socket
import sys

import pytest

from tests.support.hermetic import NetworkReachError

SIBLING_LANES = frozenset(
    {
        "patterns_pydantic_ai",
        "patterns_beeai",
        "patterns_llamaindex",
        "patterns_rag",
        "patterns_sse",
        "patterns_hitl",
        "patterns_deep_research",
    }
)


def _version(dist: str) -> tuple[int, ...]:
    return tuple(int(part) for part in importlib.metadata.version(dist).split(".")[:2])


def test_runs_on_python_315_or_later() -> None:
    assert sys.version_info >= (3, 15)


def test_fastapi_is_past_the_included_router_change() -> None:
    # 0.137 is where `_IncludedRouter` replaced flattening into `app.routes`.
    assert _version("fastapi") >= (0, 137)


def test_starlette_is_on_the_1x_line() -> None:
    assert _version("starlette") >= (1, 0)


def test_slowapi_is_not_installed() -> None:
    with pytest.raises(importlib.metadata.PackageNotFoundError):
        importlib.metadata.version("slowapi")


def test_imports_no_sibling_lane() -> None:
    importlib.import_module("patterns_rate_limit")
    assert not (SIBLING_LANES & set(sys.modules))


def test_block_network_guard_is_not_vacuous() -> None:
    with pytest.raises(NetworkReachError):
        socket.getaddrinfo("example.com", 443)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(NetworkReachError):
            sock.connect(("127.0.0.1", 6379))
        with pytest.raises(NetworkReachError):
            sock.connect_ex(("127.0.0.1", 6379))
    finally:
        sock.close()
