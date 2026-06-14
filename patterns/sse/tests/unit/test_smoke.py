"""Smoke tests for the SSE delivery lane (Spec 008-2c Req 1.1/1.3/1.4).

Task 1 scaffolds the lane as an independent uv project. This file asserts the
two structural guarantees the scaffold must hold from the very first commit:

* the lane package ``patterns_sse`` imports cleanly (Req 1.1 — the ``--locked``
  closure resolves and the editable wheel builds);
* importing it pulls in **no sibling lane** (NFR-3 / Req 1.3) — contract sharing
  flows only through the ``patterns_contracts`` path dependency, which is
  intentionally absent from the forbidden set.

The hermetic network guard and the fake one-pass live in Task 9 (``9.1``); this
file stays a pure import/boundary smoke so it can run before any pipeline code
exists.
"""

from __future__ import annotations

import importlib
import sys

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


def test_patterns_sse_imports() -> None:
    import patterns_sse

    assert patterns_sse.__name__ == "patterns_sse"


def test_no_sibling_lane_imports() -> None:
    # Import for its side effect: populate sys.modules without binding a name
    # (keeps pyright strict's reportUnusedImport quiet).
    importlib.import_module("patterns_sse")

    leaked = SIBLING_LANES & set(sys.modules)
    assert not leaked, f"SSE lane must not import sibling lanes: {sorted(leaked)}"
