"""Shared hermetic-guard exception for the Deep Research unit suite.

Lives in ``tests/support`` (not the conftest) so the autouse ``block_network``
fixture and the load-bearing guard test reference the *same* class object —
pytest imports a top-level ``conftest`` module, so a class defined there and one
imported as ``tests.unit.conftest`` would be two distinct types and
``pytest.raises`` would not match.
"""

from __future__ import annotations

__all__ = ["NetworkReachError"]


class NetworkReachError(RuntimeError):
    """Raised when a unit-lane code path attempts to reach the network (Req 8.1)."""
